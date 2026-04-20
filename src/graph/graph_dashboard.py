from pathlib import Path
import json
from dash import Dash, html, dcc, Output, Input
import dash_cytoscape as cyto
from collections import deque

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_JSON = PROJECT_ROOT / "outputs/graphs/LocationLeak1_graph.json"


# Make a JS-safe ID (some of these markers will trigger weird behavior - I found out while tryint to use "toString" as a node name)
def safe_id(node_id):
    if not node_id:
        return None
    return (
        node_id.replace('.', '_')
               .replace('$', '_')
               .replace('<', '_')
               .replace('>', '_')
               .replace(':', '_')
               .replace('-', '_')
               .replace(' ', '_')
               .lower()
    )

# Initialize app
app = Dash(__name__)

app.layout = html.Div([
    html.H1("Taint Flow Graph Explorer"),
    dcc.Store(id="graph-data-store"),  # store JSON graph
    dcc.Store(id="selected-node"),
    cyto.Cytoscape(
        id="taint-graph",
        layout={"name": "cose"},
        style={"width": "100%", "height": "800px"},
        elements=[],
        stylesheet=[
            {"selector": ".source", "style": {"background-color": "#FF4136", "label": "data(label)"}},
            {"selector": ".sink", "style": {"background-color": "#0074D9", "label": "data(label)"}},
            {"selector": ".intermediate", "style": {"background-color": "#2ECC40", "label": "data(label)"}},
            {"selector": "edge", "style": {"line-color": "#888", "target-arrow-color": "#888", "target-arrow-shape": "triangle"}},
            {"selector": ".highlighted", "style": {
                "opacity": 1,
                "line-color": "#FF4136",
                "target-arrow-color": "#FF4136",
                "width": 4
            }},
            {"selector": ".faded", "style": {
                "opacity": 0.2
            }},
        ]
    ),
    html.Div(id="node-data")
])


# Load JSON graph into Store
@app.callback(
    Output("graph-data-store", "data"),
    Input("graph-data-store", "id")
)
def load_graph(_):
    with open(GRAPH_JSON, "r") as f:
        data = json.load(f)
    print(f"[DEBUG] Loaded {len(data.get('nodes', []))} nodes and {len(data.get('edges', []))} edges")
    return data


# Save the info of a node when it's clicked on
@app.callback(
    Output("selected-node", "data"),
    Input("taint-graph", "tapNodeData")
)
def store_selected_node(node_data):
    if not node_data:
        return None
    return safe_id(node_data["id"])


# Build Cytoscape elements from Store
@app.callback(
    Output("taint-graph", "elements"),
    Input("graph-data-store", "data"),
    Input("selected-node", "data")
)
def build_elements(graph_data, selected_node):
    if not graph_data:
        return []
    
    # Add a catch to block useless nodes from being added to the graph
    USELESS_LABELS = {"append", "toString", "onResume"}

    filtered_nodes = []
    for node in graph_data.get("nodes", []):
        label = node.get("label", "")
        # Remove useless nodes
        if label in USELESS_LABELS:
            continue
        # Remove tiny meaningless labels
        if node.get("type") == "intermediate" and len(label) < 4:
            continue

        filtered_nodes.append(node)

    elements = []
    node_ids = set()
    highlight_nodes = set()
    highlight_edges = set()

    if selected_node:
        adj_forward = {}
        adj_backward = {}

        # Build adjacency lists
        for edge in graph_data["edges"]:
            src = safe_id(edge["from"])
            tgt = safe_id(edge["to"])

            adj_forward.setdefault(src, []).append(tgt)
            adj_backward.setdefault(tgt, []).append(src)

        # BFS forward
        queue = deque([selected_node])
        visited_forward = set()

        while queue:
            current = queue.popleft()
            if current in visited_forward:
                continue
            visited_forward.add(current)

            for neighbor in adj_forward.get(current, []):
                queue.append(neighbor)
                highlight_edges.add((current, neighbor))

        # BFS backward
        queue = deque([selected_node])
        visited_backward = set()

        while queue:
            current = queue.popleft()
            if current in visited_backward:
                continue
            visited_backward.add(current)

            for neighbor in adj_backward.get(current, []):
                queue.append(neighbor)
                highlight_edges.add((neighbor, current))

        highlight_nodes = visited_forward.union(visited_backward)

    # Add nodes with safe IDs
    for node in filtered_nodes:
        original_id = node.get("id")
        sid = safe_id(original_id)
        if not sid:
            continue

        node_ids.add(sid)

        node_class = node.get("type", "intermediate")

        if selected_node:
            if sid == selected_node:
                node_class += " highlighted"
            elif sid in highlight_nodes:
                node_class += " highlighted"
            else:
                node_class += " faded"

        elements.append({
            "data": {
                "id": sid,
                "label": node.get("label", sid),
                "type": node.get("type"),
                "class": node.get("class"),
                "method": node.get("method"),
                "method_name": node.get("method"),
                "line": node.get("line"),
                "raw": node.get("raw"),
                "code": node.get("code")
            },
            "classes": node_class
        })

    # Add edges using safe IDs
    for edge in graph_data.get("edges", []):
        src = safe_id(edge.get("from"))
        tgt = safe_id(edge.get("to"))
        if src in node_ids and tgt in node_ids:
            edge_class = ""
            if selected_node:
                if (src, tgt) in highlight_edges:
                    edge_class = "highlighted"
                else:
                    edge_class = "faded"

            elements.append({
                "data": {"source": src, "target": tgt},
                "classes": edge_class
            })



    print(f"[DEBUG] Total elements: {len(elements)}")
    return elements

@app.callback(
    Output("taint-graph", "layout"),
    Input("selected-node", "data")
)
def update_layout(selected_node):
    if selected_node:
        return {"name": "preset"}  # Lock layout after first click
    return {"name": "cose"}  # Initial layout


# Node click info
@app.callback(
    Output("node-data", "children"),
    Input("taint-graph", "tapNodeData"),
    Input("graph-data-store", "data")
)
def display_node_info(node_data, graph_data):
    # If nothing is clicked, show the instructions
    if not node_data or not graph_data:
        return html.Div("Click a node to see details.")

    node_id = node_data["id"]

    # Find the full node info from the stored graph
    node_info = node_data

    # Build a clean UI panel
    return html.Div([
        html.H3(node_info.get("label", "Unknown Node")),

        html.P([
            html.B("Type: "), node_info.get("type", "unknown")
        ]),

        html.P([
            html.B("Class: "), node_info.get("class", node_info.get("method", "N/A"))
        ]),

        html.P([
            html.B("Method: "), node_info.get("method", "N/A")
        ]),

        html.P([
            html.B("Line: "), str(node_info.get("line", "N/A"))
        ]),
        html.Pre(node_info.get("code") or node_info.get("label", "N/A")),

        html.H4("Code"),
        html.Pre(node_info.get("code", "N/A"), style={
            "background": "#f4f4f4",
            "padding": "10px",
            "borderRadius": "5px"
        }),

        html.H4("Raw IR"),
        html.Pre(node_info.get("raw", "N/A"), style={
            "background": "#eee",
            "padding": "10px",
            "borderRadius": "5px",
            "fontSize": "12px"
        })
    ])


# Run app
if __name__ == "__main__":
    app.run(debug=True)