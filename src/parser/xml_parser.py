import xml.etree.ElementTree as ET
from pathlib import Path
import re
import sys
import hashlib
import json


def stable_id(stmt: str) -> str:
    """
    Creates a short, consistent ID for a statement.

    Why we need this:
    - We use it as a node ID in the graph
    - Same statement always produces same ID
    """
    return hashlib.md5(stmt.encode()).hexdigest()[:10]


# *************************
# REGEX Definitions
# *************************
# Regex that matches method calls like:
# virtualinvoke obj.<Class: type method(...)>(args)
METHOD_CALL_RE = re.compile(
    r'(virtualinvoke|staticinvoke|specialinvoke|interfaceinvoke)\s+<?([^:]+):\s+([^ ]+)\s+(\w+)\((.*?)\)>?\((.*)\)'
)
# Regex that matches method calls like:
# $u2 = something
ASSIGN_RE = re.compile(r'^(.+?)\s*=\s*(.*)$')


def extract_source_line(stmt: str) -> str:
    """
    Converts FlowDroid IR (low-level representation) into a simplified Java-like assignment.

    Example input:
        lon = virtualinvoke loc.<Location: double getLongitude()>()

    Output:
        double lon = loc.getLongitude()
    """
    # Step 1: Try to match a method call pattern
    m = METHOD_CALL_RE.search(stmt)
    # If no method call if found, just return the raw statement
    if not m:
        return stmt

    # Extract parts from regex:
    # invoke_type = virtualinvoke / staticinvoke / specialinvoke
    # cls = class name (android.location.Location)
    # ret = return type (double, String, etc.)
    # method = method name (getLongitude)
    # sig = method signature (unused here)
    # args = arguments passed to method
    invoke_type, cls, ret, method, sig, args = m.groups()

    # Step 2: Convert the full JVM type name into a simple Java type
    ret = ret.split(".")[-1]

    # Step 3: Extract the left-hand side variable (e.g. lon in LocationLeak1)
    lhs = stmt.split("=")[0].strip()
    lhs = lhs.split("#")[0]

    # Step 3: Try to guess the object (receiver) calling the method
    # Example: loc.<Location: ...>
    receiver_match = re.search(r'([\w$#]+)\.<', stmt)
    # If found, use it; otherwise fallback to "obj"
    receiver = receiver_match.group(1) if receiver_match else "obj"
    # Clean receiver (remove #5 noise)
    receiver = receiver.split("#")[0]

    # Step 4: Build simplified Java-like code
    # Example:
    # double long = loc.getLongitude()
    return f"{ret} {lhs} = {receiver}.{method}()"



# *************************
# Variable Resolution
# *************************
def resolve_var(expr: str, var_map: dict) -> str:
    """
    Recursively replaces FlowDroid temporary variables ($u2, $u-1, etc.) with their resolved human-readable values.

    Example:
        input: "$u1"
        var_map:
        {"$u1": {
            'value': 'toString(double)',
            'data_type': 'String',
            'instance': '',
            'class_type': 'Double',
            'method_params': '(lon)'
        }}
        output: 'Double.toString(lon)'

    If variable is unknown, returns it as-is.
    """
    if not expr:
        return ""
    
    # First, check for statement like "this.<de.ecspride.LocationLeak1: java.lang.String latitude>" and return "latitude" i.e. the variable
    m = re.search(r'this\.<[^:]+:\s*[^>]*\s(\w+)>', expr)
    if m:
        return m.group(1)

    expr = expr.strip()

    # Remove '#' from any IR variable (i.e., longitude#3 -> longitude)
    # Only remove it from SSA suffixes though, not IR variables
    expr = re.sub(r'#\d+', '', expr)

    visited = set()

    while expr in var_map and expr not in visited:
        visited.add(expr)
        nxt = var_map[expr]
        if nxt == expr:
            break
        expr = nxt

    expr = expr.replace("staticinvoke ", "")

    return expr

# *************************
# Variable Tracking Engine
# *************************
def update_var_map(stmt: str, var_map: dict):
    """
    Tracks variable assignments and builds semantic expressions.

    Example:
        $u1 = Double.toString(lon)
        -> var_map["$u1"] = "Double.toString(lon)"
    """
    # Ignore non-assignments
    if "=" not in stmt or ":=" in stmt:
        return

    lhs, rhs = stmt.split("=", 1)
    lhs, rhs = lhs.strip(), rhs.strip()

    # Remove any "#" suffixes in the lhs and rhs ONLY IF they are not IR variablesl ike $u-1
    lhs = re.sub(r'#\d+', '', lhs)
    rhs = re.sub(r'#\d+', '', rhs)

    resolved_rhs = resolve_var(rhs, var_map)

    #var_map[lhs] = resolved_rhs
    var_map[lhs] = rhs

    # Try method call pattern
    m = METHOD_CALL_RE.search(rhs)

    if m:
        invoke_type, cls, ret, method, sig, args = m.groups()

        # Handle staticinvoke and specialinvoke statements
        if invoke_type == "staticinvoke":
            expr = parse_staticinvoke(cls, method, args, var_map)
        if invoke_type == "specialinvoke":
            # Check if the specialinvoke is a "this." call like in "PrivateDataLeak1" to produce -> this.getPassword()
            receiver_match = re.search(r'([\w$#]+)\.<', rhs)
            receiver = receiver_match.group(1).split("#")[0] if receiver_match else ""
            if receiver == "this":
                args_resolved = resolve_var(args, var_map) if args.strip() else ""
                expr = f"this.{method}({args_resolved})"
            else:
                expr = parse_staticinvoke(cls, method, args, var_map)
        
        else:
            # Extract the receiver (i.e. loc.<...> -> loc)
            receiver_match = re.search(r'([\w$#]+)\.<', rhs)
            receiver = receiver_match.group(1) if receiver_match else ""
            receiver = receiver.split("#")[0]

            args_resolved = resolve_var(args, var_map)

            # If the method parameters are variables themselves, we use the variable names, not the value
            for var, value in var_map.items():
                if args_resolved == value:
                    args_resolved = var

            # Semantic reconstruction
            if receiver:
                expr = f"{receiver}.{method}({args_resolved})"
            else:
                class_name = cls.split(".")[-1]
                expr = f"{class_name}.{method}({args_resolved})"

        var_map[lhs] = expr

        return

    # Fallback: we do direct mapping
    var_map[lhs] = resolve_var(rhs, var_map)


def reconstruct_semantic(stmt: str, var_map: dict) -> str:
    """
    Converts IR statement into Java-like readable expression.
    """
    stmt = stmt.strip()

    # Method call
    m = METHOD_CALL_RE.search(stmt)
    if m:
        _, cls, _, method, _, args = m.groups()

        class_name = cls.split(".")[-1]
        # Resolved the args -> (i.e. '"Latitude", $u2' -> Latitude, latitude)
        args = args.split(",")
        args = [arg.replace('"', "").strip() for arg in args]
        args_resolved = []
        for arg in args:
            if '$' in arg:
                arg = var_map.get(arg, arg)
            # If a resolved arg contains access$, resolve it to a field name via ret0
            if "access$" in arg:
                ret0 = var_map.get('ret0', '')
                field_match = re.search(r'<[^:]+:\s*[^\s>]+\s+(\w+)>', ret0)
                if field_match:
                    arg = field_match.group(1)
            # Handle args like "<de.ecspride.Button1: java.lang.String imei>" -> imei
            elif "<" in arg and ">":
                arg = arg.split(" ")[-1].strip(">")

            args_resolved.append(arg)

        # Make sure non-variable, non-numeric args are surrounded in quotes, variable args are not
        def is_number(s):
            """Helper for loop below"""
            try:
                float(s)
                # Account for things like "+49"
                return s.lstrip('+-').replace('.','',1).isdigit()
            except ValueError:
                return False
        for i, arg in enumerate(args_resolved):
            if arg == "null":
                pass # Keep all nulls unquoted
            elif not is_number(arg) and arg not in var_map:
                args_resolved[i] = f'"{arg}"'

        # Return either <instance>.<method> or <class>.method depending on invoke type
        instance_invoke = re.search(r'virtualinvoke\s+([^.]+)\.', stmt)
        if instance_invoke:
            instance = instance_invoke.group(1)
            return f"{instance}.{method}({", ".join(args_resolved)})"
        
        return f"{class_name}.{method}({", ".join(args_resolved)})"

    # Assignment
    if "=" in stmt:
        lhs, rhs = stmt.split("=", 1)
        lhs = lhs.strip()
        rhs_resolved = resolve_var(rhs.strip(), var_map)

        return f"{lhs} = {rhs_resolved}"

    return clean_label(stmt)


# *************************
# Filtering Logic
# *************************
def is_meaningful_node(stmt: str) -> bool:
    """
    Filters out irrelevant IR statements.

    Keeps:
    - Sources (getLatitude, getLongitude)
    - Transformations (toString)
    - Field writes

    Removes:
    - Lifecycle noise
    - StringBuilder junk
    - Compiler artifacts
    """
    s = stmt.strip()

    noise_patterns = [
        "dummyMain",
        "@parameter",
        "StringBuilder",
        "@this",
        "return",
        "<init>",
        "append(",
        "onResume()",
    ]
    if any(p in s for p in noise_patterns):
        return False

    if "getLatitude" in s or "getLongitude" in s:
        return True

    if "Double: java.lang.String toString" in s:
        return True

    if re.search(r'\.<.*>\s*=', s):  # field write
        return True

    return True


def parse_method_signature(method_sig: str):
    """
    Extract class name and method name from FlowDroid signature.
    Example:
        <de.ecspride.LocationLeak1: void onResume()> -> ("LocationLeak1", "onResume")
    """
    if not method_sig:
        return ("unknown", "unknown")
    m = re.search(r'<([\w\.\$]+):\s+[\w\.\[\]]+\s+(\w+)\(', method_sig)
    if not m:
        return ("unknown", "unknown")
    full_class = m.group(1)
    method = m.group(2)
    simple_class = full_class.split(".")[-1]
    return (simple_class, method)


def clean_label(stmt: str) -> str:
    """Make the statement for intermediate nodes cleaner"""
    s = stmt.strip()

    if "virtualinvoke" in s:
        m = re.search(r"<([^:]+): .* (\w+)\(", s)
        if m:
            return m.group(2)

    if "staticinvoke" in s:
        m = re.search(r"<([^:]+): .* (\w+)\(", s)
        if m:
            return m.group(2)

    return s[:40]




# *************************
# STAGE 1: XML EXTRACTION
# *************************
def extract_raw_paths(root):
    """
    Extracts raw taint paths from FlowDroid XML.

    Output format:
    [
        {
            "source": {...},
            "path": [stmt1, stmt2, ...],
            "sink": {...}
        }
    ]
    """
    paths = []

    for result in root.findall(".//Result"):
        sources_elem = result.find("Sources")
        sink_elem = result.find("Sink")

        if sources_elem is None or sink_elem is None:
            # Pass if source or sink not found
            continue

        # ---- Extract sink access path ----
        sink_ap_elem = sink_elem.find("AccessPath")
        sink_ap = sink_ap_elem.attrib if sink_ap_elem is not None else {}

        for source_elem in sources_elem.findall("Source"):
            path_elems = source_elem.find("TaintPath")

            # ---- Extract source access path ----
            source_ap_elem = source_elem.find("AccessPath")
            source_ap = source_ap_elem.attrib if source_ap_elem is not None else {}

            path_statements = []
            if path_elems is not None:
                for pe in path_elems.findall("PathElement"):
                    
                    # ---- Extract intermediate access path ----
                    ap_elem = pe.find("AccessPath")
                    ap = ap_elem.attrib if ap_elem is not None else {}

                    # Append each path elements "Statement" and "Method", and <AccessPath>
                    path_statements.append({
                        "stmt": pe.attrib.get("Statement"),
                        "method": pe.attrib.get("Method"),
                        "access_path": ap
                    })

            # Add all attributes of <PathElement> and <AccessPath> into one dict
            paths.append({
                "source": {
                    **source_elem.attrib,
                    "access_path": source_ap
                },
                "path": path_statements,
                "sink": {
                    **sink_elem.attrib,
                    "access_path": sink_ap
                }
            })
        
    return paths


# *************************
# STAGE 2: PATH PROCESSING (helpers below)
# *************************
def extract_access_paths(raw_path):
    """
    Helper function to track all <AccessPath> tag variables

    Example Output: {"lon", "lat", "$u2", "$u-1", "longitude", "latitude"}
    """
    vars = set()

    # Source
    src_ap = raw_path["source"].get("access_path", {})
    if "Value" in src_ap:
        vars.add(src_ap["Value"])
    
    # Sink
    sink_ap = raw_path["sink"].get("access_path", {})
    if "Value" in sink_ap:
        vars.add(sink_ap["Value"])
    
    # All path elements
    for elem in raw_path["path"]:
        ap = elem.get("access_path", {})
        if "Value" in ap:
            vars.add(ap["Value"])
    
    return vars

def involves_tracked_data(expr: str, access_vars: set):
    """Helper function to see if an expression is in a <AccessPath> tag"""
    for v in access_vars:
        if v in expr:
            return True
    return False

def extract_last_field(lhs: str) -> str:
    """
    Extracts:
    this.<Class: type field>
    $u0.<Class: type field>
    -> field
    """
    # Match last word inside < ... >
    m = re.search(r'<[^:]+:\s*[^>]*\s(\w+)>', lhs)
    if m:
        return m.group(1)

    # fallback: this / $uX etc
    if lhs.startswith("this"):
        return "this"

    if lhs.startswith("$"):
        return lhs.split(".")[0]

    return lhs.strip()

def handle_access_stmt(stmt: str, ap: dict, var_map: dict):
    """
    Handle access statements, which map intermediate variables to new values.
    
    Example:
    stmt -> staticinvoke <de.ecspride.LocationLeak1: void access$1(de.ecspride.LocationLeak1,java.lang.String)>($u4, $u-1)
    ap -> {'Value': '$u1', 'Type': 'java.lang.String', 'TaintSubFields': 'true'}
    var_map -> {
                'lon': 'loc.getLongitude()',
                '$u-1': 'Double.toString(lon)'
                }

    Function will update var_map:
    var_map -> {
                'lon': 'loc.getLongitude()',
                '$u-1': 'Double.toString(lon)',
                '$u1': 'Double.toString(lon)'
                }
    """
    if not ap['TaintSubFields']:
        return

    args_match = re.search(r'\(([^)]*)\)\s*$', stmt)
    args = args_match.group(1) if args_match else ""

    # Get the variable who's value will be mapped to (i.e. $u-1)
    variable = args.split(",")[-1].strip()

    if variable in var_map:
        var_map[ap["Value"]] = var_map[variable]

def normalize_label(label: str) -> str:
    """Treat standalone 'null' assignments as literals (no parens needed). Do NOT strip parens from method calls that merely contain null as an argument."""
    if re.match(r'^\s*\S+\s*=\s*null\s*$', label):
        label = label.replace("(", "").replace(")", "")
    return label

def parse_staticinvoke(cls, method, args, var_map):
    """
    Converts:
    staticinvoke <java.util.Arrays: java.lang.String toString(java.lang.Object[])>(array)

    Into:
    Arrays.toString(array)
    """

    class_name = cls.split(":")[0].split(".")[-1]

    # Split args safely
    args_resolved = ""
    if args not in var_map:
        args_resolved = resolve_var(args, var_map)

    args_resolved = args_resolved.split(",")
    args_resolved = [a.strip() for a in args_resolved if a.strip()]

    if args_resolved:
        return f"{class_name}.{method}({', '.join(args_resolved)})"
    return f"{class_name}.{method}({args})"

# *************************
# STAGE 2: PATH PROCESSING (main path processing below)
# *************************
def process_path(raw_path):
    """
    Converts raw IR path into meaningful graph nodes.

    Returns:
    [
        (node_id, node_label, node_type, IR statement),
        ...
    ]
    """
    access_vars = extract_access_paths(raw_path)
    var_map = {}
    processed_nodes = []
    source_added = False # Track and properly label the source node


    # ---- SOURCE ----
    source_stmt = raw_path["source"].get("Statement")
    source_label = normalize_label(extract_source_line(source_stmt))

    # Get the class and method in which this line occurred
    class_name, method_name = parse_method_signature(raw_path["source"].get("Method"))

    # Check if the source stmt is an assignment
    lhs_match = ASSIGN_RE.search(source_stmt)
    raw_lhs = ""
    if lhs_match:
        raw_lhs = lhs_match.group(1)
    
    # Only append the source statment if it's a real variable assignment
    if "$" not in raw_lhs:
        source_added = True
        processed_nodes.append((
            stable_id(source_label),
            source_label,
            "source",
            source_stmt,
            raw_path["source"].get("LineNumber"),
            class_name,
            method_name
        ))

    update_var_map(source_stmt, var_map)

    # Track latest meaningful assignments (i.e. longitude = Double.toString(long))
    latest_values = {}

    # ---- INTERMEDIATE ----
    i = 1
    for elem in raw_path["path"]:
        i += 1
        stmt = elem.get("stmt")

        if not stmt or not is_meaningful_node(stmt):
            continue

        # Track variables first (i.e. $u1, $u2, etc.)
        update_var_map(stmt, var_map)

        ap = elem.get("access_path", {})
        if "Value" in ap and "access" in stmt:
            handle_access_stmt(stmt, ap, var_map)

        # Detect real assignments only
        lhs_match = ASSIGN_RE.search(stmt)

        if not lhs_match or "#" in lhs_match.group(1):
            continue

        raw_lhs = lhs_match.group(1)

        rhs = lhs_match.group(2)

        # Extract lhs field (i.e. $u0.<Class: type field> -> field)
        lhs = extract_last_field(raw_lhs)

        # Preserve "this." in the lhs if it's something like this.<Class: type field> = ...
        lhs_display = lhs
        if raw_lhs.startswith("this.") or raw_lhs == "this":
            lhs_display = f"this.{lhs}"

        # Skip if lhs of resolved statment = "this"
        if "this" == lhs:
            continue

        # Replace raw_lhs in the var map if it's in there and use the resolved version
        if raw_lhs in var_map:
            var_map[lhs] = var_map.pop(raw_lhs)

        resolved = ""
        # Try to get the value of the rhs in the map
        if rhs not in var_map:
            resolved = resolve_var(rhs, var_map)
        # If the rhs not in var_map, construct it's java representation
        if resolved == "":
            resolved = reconstruct_semantic(rhs, var_map)

        # 2) Detct ONLY meaningful variables
        label = ""
        if involves_tracked_data(stmt, access_vars) or involves_tracked_data(resolved, access_vars):
            label = normalize_label(reconstruct_semantic(stmt, var_map))
            if rhs in var_map:
                # While rhs is a temp variable (i.e. '$u1', resolve it until it's a normal value)
                while "$" in rhs and rhs in var_map:
                    rhs = var_map[rhs]
                label = f"{lhs_display} = {rhs}"
                var_map[lhs] = rhs
            elif lhs in var_map:
                label = f"{lhs_display} = {var_map[lhs]}"
            elif resolved:
                label = f"{lhs_display} = {resolved}"
            else:
                label = f"{lhs_display} = {rhs}"
        
        # De-duplicate identical semantic states
        if stmt != source_stmt and stmt != raw_path["sink"].get("Statement") and label and ("$" not in label) and latest_values.get(lhs) != label:
            latest_values[lhs] = label

            # Get the method and class in which this line occurred
            class_name, method_name = parse_method_signature(elem.get("method"))
            if source_added:
                # Source already added
                processed_nodes.append((
                    stable_id(label),
                    extract_source_line(label),
                    "intermediate",
                    stmt,
                    None,
                    class_name,
                    method_name
                ))
            else:
                # This is the source node
                source_added = True
                processed_nodes.append((
                    stable_id(label),
                    label,
                    "source",
                    stmt,
                    None,
                    class_name,
                    method_name
                ))
    
    # ---- SINK ----
    sink_stmt = raw_path["sink"].get("Statement")
    sink_label = reconstruct_semantic(sink_stmt, var_map)
    sink_label = normalize_label(extract_source_line(sink_label))
    # Get the method and class in which this line occurred
    class_name, method_name = parse_method_signature(elem.get("method"))


    processed_nodes.append((
        stable_id(f"{sink_label}:{raw_path["sink"].get("LineNumber")}:{class_name}:{method_name}"),
        sink_label,
        "sink",
        sink_stmt,
        raw_path["sink"].get("LineNumber"),
        class_name,
        method_name
    ))

    return processed_nodes


# *************************
# STAGE 3: GRAPH BUILDER
# *************************
def parse_flowdroid_xml(file_path: str):
    """
    Main pipeline:

    1. Parse XML
    2. Extract raw paths
    3. Process each path
    4. Build graph

    Output:
    {
        "nodes": [...],
        "edges": [...]
    }
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"{file_path} does not exist")

    # Guard against empty output file (FlowDroid found no results) so our output is clear to users
    content = file_path.read_text().strip()
    if not content:
        raise RuntimeError("FlowDroid produced no output - no sources/sinks found in this APK.")
    
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Extract raw IR statements
    raw_paths = extract_raw_paths(root)

    nodes = []
    edges = []
    # Keep track of node and edge IDs to avoid duplicates
    node_set = set()
    edge_set = set()

    # ---- PROCESS EACH PATH ----
    for raw_path in raw_paths:
        processed = process_path(raw_path)

        # Build nodes + edges linearly
        for i, node in enumerate(processed):
            nid, label, ntype, raw, line, class_name, method_name = node

            if nid not in node_set:
                nodes.append({
                    "id": nid,
                    "label": label,
                    "type": ntype,
                    "raw": raw,
                    "code": label,
                    "line": line,
                    "class": class_name,
                    "method": method_name
                })
                node_set.add(nid)

            # Connect edges
            if i > 0:
                prev_id = processed[i - 1][0]
                edge = (prev_id, nid)

                if edge not in edge_set:
                    edges.append({"from": prev_id, "to": nid})
                    edge_set.add(edge)

    # Finally, filter out any nodes that don't have incident edges
    # Collect all node IDs that appear in at least one edge
    connected_ids = set()
    for edge in edges:
        connected_ids.add(edge["from"])
        connected_ids.add(edge["to"])

    # Keep only nodes that are connected
    nodes = [node for node in nodes if node["id"] in connected_ids]

    return {
        "nodes": nodes,
        "edges": edges
    }



if __name__ == "__main__":
    import json
    if len(sys.argv) != 2:
        print("Usage: python3 xml_parser.py <XML_NAME>")
        sys.exit(1)
    try:
        # Fetch the XML file
        xml_file = f"data/xml_results/{sys.argv[1]}.xml"
        # Parse the XML file
        parsed = parse_flowdroid_xml(xml_file)
    except Exception as e:
        print(f"[xml_parser.py] Error: {e}")
