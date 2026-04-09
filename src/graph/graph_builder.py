import networkx as nx
import json
import sys
import os

# Add src folder to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from parser.xml_parser import parse_flowdroid_xml # import our xml_parser


def build_graph(parsed_data):
    """
    Builds a NetworkX directed graph from parsed FlowDroid data.
    Args:
        parsed_data (dict) : dict with "nodes" and "edges"
    Returns:
        networkx.DiGraph
    """
    G = nx.DiGraph()
    seen_edges = set()
    intermediate_count = 0
    id_map = {}  # Map original IDs to short IDs

    # Add nodes
    for node in parsed_data["nodes"]:
        orig_id = node["id"]
        node_type = node.get("type", "intermediate")
        if node_type == "intermediate":
            intermediate_count += 1
            short_id = f"i{intermediate_count}"
            id_map[orig_id] = short_id
        else:
            short_id = orig_id
            id_map[orig_id] = short_id

        G.add_node(short_id, **node)

    # Add edges, skipping self-loops and duplicates
    for edge in parsed_data["edges"]:
        u_orig = edge["from"]
        v_orig = edge["to"]

        if u_orig not in id_map or v_orig not in id_map:
            continue

        u = id_map[u_orig]
        v = id_map[v_orig]

        if u != v and (u, v) not in seen_edges:
            G.add_edge(u, v)
            seen_edges.add((u, v))

    return G


def export_json(G, output_path):
    """
    Exports NetworkX graph to JSON format (nodes and edges).
    """
    data = {
        "nodes": [],
        "edges": []
    }

    for node, attrs in G.nodes(data=True):
        node_data = dict(attrs)
        node_data["id"] = node  # force ID to match graph node key
        data["nodes"].append(node_data)

    for u, v in G.edges():
        data["edges"].append({"from": u, "to": v})

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 graph_builder.py <XML_NAME>")
        sys.exit(1)

    # Get the XML input file and JSON output file paths
    xml_name = sys.argv[1]
    xml_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "xml_results", f"{xml_name}.xml")
    output_file = os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "graphs", f"{xml_name}_graph.json")

    # Parse the XML file -> JSON format
    parsed = parse_flowdroid_xml(xml_file)
    G = build_graph(parsed)
    export_json(G, output_file)

    print(f"Graph exported successfully to {output_file}")