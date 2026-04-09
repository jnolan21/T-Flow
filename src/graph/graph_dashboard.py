from pathlib import Path
import json
from dash import Dash, html, dcc, Output, Input
import dash_cytoscape as cyto

# -------------------------------
# Paths
# -------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_JSON = PROJECT_ROOT / "outputs/graphs/LocationLeak1_graph.json"

# -------------------------------
# Make a JS-safe ID
# -------------------------------
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
               .lower()  # optional: normalize case
    )

# -------------------------------
# Initialize app
# -------------------------------
app = Dash(__name__)

app.layout = html.Div([
    html.H1("Taint Flow Graph Explorer"),
    dcc.Store(id="graph-data-store"),  # store JSON graph
    cyto.Cytoscape(
        id="taint-graph",
        layout={"name": "cose"},
        style={"width": "100%", "height": "800px"},
        elements=[],  # initially empty
        stylesheet=[
            {"selector": ".source", "style": {"background-color": "#FF4136", "label": "data(label)"}},
            {"selector": ".sink", "style": {"background-color": "#0074D9", "label": "data(label)"}},
            {"selector": ".intermediate", "style": {"background-color": "#2ECC40", "label": "data(label)"}},
            {"selector": "edge", "style": {"line-color": "#888", "target-arrow-color": "#888", "target-arrow-shape": "triangle"}}
        ]
    ),
    html.Div(id="node-data")
])

# -------------------------------
# Load JSON graph into Store
# -------------------------------
@app.callback(
    Output("graph-data-store", "data"),
    Input("graph-data-store", "id")
)
def load_graph(_):
    with open(GRAPH_JSON, "r") as f:
        data = json.load(f)
    print(f"[DEBUG] Loaded {len(data.get('nodes', []))} nodes and {len(data.get('edges', []))} edges")
    return data

# -------------------------------
# Build Cytoscape elements from Store
# -------------------------------
@app.callback(
    Output("taint-graph", "elements"),
    Input("graph-data-store", "data")
)
def build_elements(graph_data):
    if not graph_data:
        return []

    elements = []
    node_ids = set()

    # Add nodes with safe IDs
    for node in graph_data.get("nodes", []):
        original_id = node.get("id")
        sid = safe_id(original_id)
        if not sid:
            continue
        node_ids.add(sid)
        elements.append({
            "data": {"id": sid, "label": sid},  # label is just the safe ID
            "classes": node.get("type", "intermediate")
        })

    # Add edges using safe IDs
    for edge in graph_data.get("edges", []):
        src = safe_id(edge.get("from"))
        tgt = safe_id(edge.get("to"))
        if src in node_ids and tgt in node_ids:
            elements.append({"data": {"source": src, "target": tgt}})

    print(f"[DEBUG] Total elements: {len(elements)}")
    return elements

# -------------------------------
# Node click info
# -------------------------------
@app.callback(
    Output("node-data", "children"),
    Input("taint-graph", "tapNodeData"),
    Input("graph-data-store", "data")
)
def display_node_info(node_data, graph_data):
    if not node_data or not graph_data:
        return "Click a node to see details."

    node_id = node_data["id"]
    node_info = next(
        (n for n in graph_data.get("nodes", []) if safe_id(n.get("id")) == node_id),
        {}
    )
    return json.dumps(node_info, indent=2)

# -------------------------------
# Run app
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True)