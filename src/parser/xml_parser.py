import xml.etree.ElementTree as ET
from pathlib import Path
import re
import sys
import hashlib


def stable_id(stmt: str) -> str:
    """Get a stable hash to use for the id of intermediate nodes"""
    return hashlib.md5(stmt.encode()).hexdigest()[:10]

def extract_short_id(statement: str):
    """
    Generate a more unique and readable ID for a FlowDroid statement.
    - For sources: use the method name (getLatitude, getLongitude)
    - For sinks: include method name + first literal argument if present (Log.d_Latitude)
    - For intermediates: fallback to statement but remove extra spaces/newlines
    """
    # Try to match a method inside <>
    method_match = re.search(r"<[^:]+: [^ ]+ (\w+)\(", statement)
    literal_match = re.search(r'\("([^"]+)"', statement)  # get first quoted literal, e.g. "Latitude"

    if method_match:
        base = method_match.group(1)
        if literal_match:
            return f"{base}_{literal_match.group(1)}"
        return base

    # Remove line breaks and truncate to 60 chars for intermediates
    clean = statement.replace("\n", " ").strip()
    return clean[:60]

def extract_sink_line(sink_stmt: str, sink_elem) -> str:
    """
    Reconstruct a Java-like sink line from FlowDroid IR + AccessPath.
    Example:
        staticinvoke Log.d("Latitude", $u2)
        -> Log.d(latitude)
    """
    pattern = r'staticinvoke\s+<([^:]+):.*?\s(\w+)\(.*?\)>\((.*)\)'
    match = re.search(pattern, sink_stmt)

    if not match:
        return sink_stmt
    
    class_path, method, args = match.groups()

    # Get simple class name (ex: Log from android.util.Log)
    class_name = class_path.split(".")[-1]

    # Get AccessPath values (ex. <AccessPath Value="lon" Type="double" TaintSubFields="true"/> -> {"lon": "double"})
    access_paths = {}
    for ap in sink_elem.findall("AccessPath"):
        access_paths[ap.attrib.get("Value")] = ap.attrib.get("Type")

    # Split args (ex: Longitude from ("Longtitude", $u2))
    arg_list = [a.strip() for a in args.split(',')]

    resolved_args = []
    for arg in arg_list:
        arg = arg.strip().strip('"')

        if arg.startswith("$"):
            # Try to resolve via AccessPath
            if arg in access_paths:
                # Convert type to readable var name
                type = access_paths[arg]
                simple = type.split(".")[-1].lower()
                resolved_args.append(simple)
            else:
                resolved_args.append("unknown")
        else:
            resolved_args.append(arg.lower())
        
    return f"{class_name}.{method}({', '.join(resolved_args)})"


def extract_source_line(source_stmt: str, source_elem) -> str:
    """
    Reconstruct a Java-like source line from FlowDroid IR.
    Example:
        lon = virtualinvoke loc.<Location: double getLongitude()>()
        -> double lon = loc.getLongitude()
    """
    # Match: lhs = virtualinvoke receiver.<class: returnType method()>
    pattern = r'(\$\w+|\w+)\s*=\s*virtualinvoke\s+(\w+)\.<([^:]+):\s*([^ ]+)\s+(\w+)\(\)>'
    match = re.search(pattern, source_stmt)

    if not match:
        return source_stmt
    
    lhs, receiver, class_path, return_type, method = match.groups()
    
    # Get the clean types
    simple_type = return_type.split(".")[-1]
    class_name = class_path.split(".")[-1]

    # Map each variable in the AccessPath to it's type (ex. "lon" -> "double")
    access_map = {}
    for ap in source_elem.findall("AccessPath"):
        access_map[ap.attrib.get("Value")] = ap.attrib.get("Type")

    var_name = lhs
    if lhs in access_map:
        var_name = lhs

    # Build Java-like line
    return f"{simple_type} {var_name} = {receiver}.{method}()"

def classify_node(stmt: str) -> str:
    """Helper to check if a statement is "noise", or nonsense"""
    s = stmt.strip()

    if "access$" in s:
        return "noise"

    if "dummyMain" in s:
        return "noise"

    if "@parameter" in s or "@this" in s:
        return "noise"

    if "specialinvoke" in s and "<init>" in s:
        return "noise"

    if "virtualinvoke" in s or "staticinvoke" in s:
        return "semantic"

    if "=" in s:
        return "assign"

    return "unknown"

def reconstruct_java_line(stmt: str) -> str:
    """Reconstruct the original Java source code line for a statement"""
    s = stmt.strip()

    # Pattern 1: Double.toString(x)
    m = re.search(
        r'(\$\S+)\s*=\s*staticinvoke\s+<java\.lang\.Double:\s+java\.lang\.String\s+toString\(double\)>\((\w+)\)',
        s
    )
    if m:
        _, var = m.groups()
        return f"String tmp = Double.toString({var});"

    # Pattern 2: field write
    m = re.search(
        r'<[^:]+:\s+([\w\.]+)\s+(\w+)>\s*=\s*(\$\S+)',
        s
    )
    if m:
        _, field, rhs = m.groups()
        return f"{field} = {rhs};"

    # Pattern 3: StringBuilder append
    m = re.search(r'append\((\$\w+)\)', s)
    if m:
        return f"append({m.group(1)})"

    # fallback
    return clean_label(stmt)

def is_meaningful_node(stmt: str) -> bool:
    # Skip compiler-generated accessor methods and very short generic statements
    s = stmt.strip()

    # 1) Remove lifecycle + builder noise
    noise_patterns = [
        "access$",
        "dummyMain",
        "@parameter",
        "@this",
        "return",
        "<init>",
        "StringBuilder",
        "append(",
        "toString()",
        "onResume()",
    ]
    if any(p in s for p in noise_patterns):
        return False

    # 2) Keep only real data movement
    if "getLatitude" in s or "getLongitude" in s:
        return True

    if "Double: java.lang.String toString" in s:
        return True

    if re.search(r'\.<.*>\s*=', s):  # field write
        return True

    return False

def parse_method_signature(method_sig: str):
    """
    Extract class name and method name from FlowDroid signature.
    Example:
        <de.ecspride.LocationLeak1: void onResume()>
        -> ("LocationLeak1", "onResume")
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


def parse_flowdroid_xml(file_path: str):
    """
    Parses a FlowDroid XML log and extracts the sources, sinks, and intermediate variables.
    Returns: dict with "nodes" and "edges" suitable for graph construction.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"{file_path} does not exist")
    
    tree = ET.parse(file_path)
    root = tree.getroot()

    nodes = []
    edges = []

    # Keep track of node and edge IDs to avoid duplicates
    node_set = set()
    edge_set = set()

    # Iterate through each <Result> tag in the XML
    for result in root.findall(".//Result"):
        # Extract the sink
        sink_elem = result.find("Sink")
        if sink_elem is None:
            continue
        sink_stmt = sink_elem.attrib.get("Statement")
        sink_method = sink_elem.attrib.get("Method")
        sink_id = stable_id(sink_stmt)
        sink_name = extract_sink_line(sink_stmt, sink_elem)
        sink_line = sink_elem.attrib.get("LineNumber")
        cls, method_name = parse_method_signature(sink_method)

        if sink_id not in node_set:
            nodes.append({
                "id": sink_id,
                "label": sink_name, # Reconstructed Java-like line
                "raw": sink_stmt, # Original IR for debugging
                "type": "sink",
                "class": cls,
                "method": method_name,
                "full_method": sink_method,
                "line": sink_line
            })
            node_set.add(sink_id)
        
        # Extract sources
        sources_elem = result.find("Sources")
        if sources_elem is None:
            continue
            
        for source_elem in sources_elem.findall("Source"):
            print(source_elem)
            source_stmt = source_elem.attrib.get("Statement")
            source_method = source_elem.attrib.get("Method")
            source_id = stable_id(source_stmt)
            source_name = extract_source_line(source_stmt, source_elem)
            source_line = source_elem.attrib.get("LineNumber")
            cls, method_name = parse_method_signature(source_method)

            if source_id not in node_set:
                nodes.append({
                    "id": source_id,
                    "label": source_name,
                    "raw": source_stmt,
                    "type": "source",
                    "class": cls,
                    "method": method_name,
                    "full_method": source_method,
                    "line": source_line
                })
                node_set.add(source_id)

            # Extract the taint path elements as the intermediate edges
            taint_path = source_elem.find("TaintPath")
            if taint_path is not None:
                last_var = source_id
                pending_conversion = None

                for path_elem in taint_path.findall("PathElement"):
                    intermediate_stmt = path_elem.attrib.get("Statement")
                    intermediate_method = path_elem.attrib.get("Method")

                    if not is_meaningful_node(intermediate_stmt):
                        continue

                    # 1) Detect Double.toString
                    if "Double: java.lang.String toString" in intermediate_stmt:
                        m = re.search(r'\((\w+)\)', intermediate_stmt)
                        if m:
                            pending_conversion = m.group(1)
                        continue

                    # 2) Detect field write
                    field_match = re.search(
                        r'<[^:]+:\s+java\.lang\.String\s+(\w+)>',
                        intermediate_stmt
                    )

                    if field_match and pending_conversion:
                        field_name = field_match.group(1)

                        label = f"{field_name} = Double.toString({pending_conversion});"
                        intermediate_id = stable_id(label)

                        if intermediate_id not in node_set:
                            nodes.append({
                                "id": intermediate_id,
                                "label": label,
                                "type": "intermediate",
                                "method": intermediate_method
                            })
                            node_set.add(intermediate_id)

                        edge = (last_var, intermediate_id)
                        if edge not in edge_set:
                            edges.append({"from": last_var, "to": intermediate_id})
                            edge_set.add(edge)

                        last_var = intermediate_id
                        pending_conversion = None
                        continue

                # connect to sink
                edge = (last_var, sink_id)
                if edge not in edge_set:
                    edges.append({"from": last_var, "to": sink_id})
                    edge_set.add(edge)

    return {
        "nodes": nodes,
        "edges": edges
    }


if __name__ == "__main__":
    import json
    if len(sys.argv) != 2:
        print("Usage: python3 xml_parser.py <XML_NAME>")
        sys.exit(1)
    # Fetch the XML file
    xml_file = f"data/xml_results/{sys.argv[1]}.xml"
    # Parse the XML file
    parsed = parse_flowdroid_xml(xml_file)
    print(json.dumps(parsed, indent=2))