import xml.etree.ElementTree as ET
from pathlib import Path
import re
import sys


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


def is_meaningful_node(statement):
    # Skip compiler-generated accessor methods and very short generic statements
    if statement.startswith("staticinvoke <de.ecspride.LocationLeak1: void access$"):
        return False
    if statement.strip() in ("return", "this := @this"):
        return False
    return True


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

    # Keep track of node IDs to avoid duplicates
    node_set = set()

    # Iterate through each <Result> tag in the XML
    for result in root.findall(".//Result"):
        # Extract the sink
        sink_elem = result.find("Sink")
        if sink_elem is None:
            continue
        sink_stmt = sink_elem.attrib.get("Statement")
        sink_method = sink_elem.attrib.get("Method")
        sink_id = extract_short_id(sink_stmt)

        if sink_id not in node_set:
            nodes.append({
                "id": sink_id,
                "label": sink_stmt,
                "type": "sink",
                "method": sink_method
            })
            node_set.add(sink_id)
        
        # Extract sources
        sources_elem = result.find("Sources")
        if sources_elem is None:
            continue
            
        for source_elem in sources_elem.findall("Source"):
            source_stmt = source_elem.attrib.get("Statement")
            source_method = source_elem.attrib.get("Method")
            source_id = extract_short_id(source_stmt)

            if source_id not in node_set:
                nodes.append({
                    "id": source_id,
                    "label": source_stmt,
                    "type": "source",
                    "method": source_method
                })
                node_set.add(source_id)

            # Extract the taint path elements as the intermediate edges
            taint_path = source_elem.find("TaintPath")
            if taint_path is not None:
                last_var = source_id
                for path_elem in taint_path.findall("PathElement"):
                    intermediate_stmt = path_elem.attrib.get("Statement")
                    intermediate_method = path_elem.attrib.get("Method")
                    intermediate_id = extract_short_id(intermediate_stmt)

                    # Skip meaningless compiler-generated intermediates
                    if not is_meaningful_node(intermediate_stmt):
                        continue

                    if intermediate_id not in node_set:
                        nodes.append({
                            "id": intermediate_id,
                            "label": intermediate_stmt,
                            "type": "intermediate",
                            "method": intermediate_method
                        })
                        node_set.add(intermediate_id)
                    
                    # Connect last node -> current intermediate
                    edges.append({
                        "from": last_var,
                        "to": intermediate_id
                    })
                    last_var = intermediate_id
                
                # Finally, connect the last intermediate -> sink
                edges.append({
                    "from": last_var,
                    "to": sink_id
                })
            else:
                # Direct edge from source -> sink
                edges.append({
                    "from": source_id,
                    "to": sink_id
                })

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