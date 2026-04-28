from pathlib import Path
import json
import sys
from dash import Dash, html, dcc, Output, Input
import dash_cytoscape as cyto
from collections import deque

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Discover the available graphs in "outputs/graphs"
GRAPH_DIR = PROJECT_ROOT / "outputs/graphs"
def get_available_graphs():
    """Search "outputs/graphs" and find all {name}_graph.json files as viable graphs to display"""
    graph_options = []
    for f in GRAPH_DIR.glob("*_graph.json"):
        graph_options.append(f.stem.replace("_graph", ""))
    return sorted(graph_options)

# Get all the available graphs to display
AVAILABLE_GRAPHS = get_available_graphs()


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

    # Header
    html.H1("Taint Flow Graph Explorer", style={
        "textAlign": "center",
        "marginBottom": "20px"
    }),
    dcc.Store(id="graph-data-store"),
    dcc.Store(id="selected-node"),

    # Main dashboard container
html.Div([

    # Left: Graph Panel
    html.Div([
        dcc.Checklist(
            id="simplify-toggle",
            options=[{"label": "Show only Source → Sink", "value": "simplify"}],
            value=[],
            style={
                "marginBottom": "10px",
                "flex": "3",
                "border": "2px solid #ccc",
                "borderRadius": "8px",
                "padding": "10px",
                "marginRight": "10px",
            }
        ),
        dcc.Dropdown(
            id="graph-selector",
            options=[{"label": name, "value": name} for name in AVAILABLE_GRAPHS],
            value=AVAILABLE_GRAPHS[0] if AVAILABLE_GRAPHS else None,
            placeholder="Select a program...",
            style={"marginBottom": "15px"}
        ),
        html.H3("Graph View"),
        cyto.Cytoscape(
            id="taint-graph",
            layout={
                "name": "breadthfirst",
                "directed": True,
                "orientation": "horizontal",
                "spacingFactor": 1.8,
                "padding": 10,
                "roots": '[type = "source"]',
                "animate": False
            },
            style={"width": "100%", "height": "700px"},
            elements=[],
            stylesheet=[
                {
                    "selector": "node",
                    "style": {
                        "label": "data(label)",
                        "font-size": "10px",
                        "text-wrap": "wrap",
                        "text-max-width": "120px",
                        "text-valign": "top",
                        "text-halign": "left"
                    }
                },
                {"selector": ".source", "style": {"background-color": "#FF4136", "label": "data(label)"}},
                {"selector": ".sink", "style": {"background-color": "#0074D9", "label": "data(label)"}},
                {"selector": ".intermediate", "style": {"background-color": "#2ECC40", "label": "data(label)"}},
                {"selector": "edge", "style": {
                    "line-color": "#888",
                    "target-arrow-color": "#888",
                    "target-arrow-shape": "triangle",
                    "arrow-scale": 1.5,
                    "curve-style": "bezier"
                    }
                },
                {"selector": "edge.highlighted", "style": {
                    "line-color": "#FF4136",
                    "target-arrow-color": "#FF4136",
                    "width": 4
                }},
                {"selector": "node.highlighted", "style": {
                    "opacity": 1,
                    "border-width": 2,
                    "border-color": "#FF4136"
                }},
                {"selector": ".faded", "style": {"opacity": 0.2}},
            ]
        )
    ], style={
        "flex": "3",
        "border": "2px solid #ccc",
        "borderRadius": "8px",
        "padding": "10px",
        "marginRight": "10px",
        "backgroundColor": "#ffffff"
    }),

    # Right: Info Panel
    html.Div([
        html.Div([
            html.H3("Node Details"),
            html.Div(
                id="node-data",
                style={
                    "minHeight": "150px",
                    "padding": "10px",
                    "backgroundColor": "#fafafa"
                }
            )
        ], style={
            "border": "2px solid #ccc",
            "borderRadius": "8px",
            "padding": "10px",
            "marginBottom": "10px"
        }),
        html.Div([
            html.H3("Path View"),
            html.Div(id="path-data")
        ], style={
            "border": "2px solid #ccc",
            "borderRadius": "8px",
            "padding": "10px",
            "marginBottom": "10px"
        }),
        html.Div([
            html.H3("Graph Stats"),
            html.Div(id="graph-stats")
        ], style={
            "border": "2px solid #ccc",
            "borderRadius": "8px",
            "padding": "10px"
        })

    ], style={
        "flex": "1",
        "display": "flex",
        "flexDirection": "column"
    })

], style={
    "display": "flex",
    "padding": "10px"
})
])

@app.callback(
    Output("path-data", "children"),
    Input("selected-node", "data"),
    Input("graph-data-store", "data")
)
def display_path(selected_node, graph_data):
    """Calculate the path in the graph for a selected node to display in the info panel"""
    if not selected_node or not graph_data:
        return "Click a node to see its full path."

    # Build adjacency dictionaries
    adj_forward = {}
    adj_backward = {}

    for edge in graph_data["edges"]:
        src = safe_id(edge["from"])
        tgt = safe_id(edge["to"])

        adj_forward.setdefault(src, []).append(tgt)
        adj_backward.setdefault(tgt, []).append(src)

    # BFS backward to find sources for the selected node
    sources = []
    queue = [selected_node]
    visited = set()

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)

        if curr not in adj_backward:
            sources.append(curr)

        for prev in adj_backward.get(curr, []):
            queue.append(prev)

    # BFS forward to find sinks for the selected node
    sinks = []
    queue = [selected_node]
    visited = set()

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)

        if curr not in adj_forward:
            sinks.append(curr)

        for nxt in adj_forward.get(curr, []):
            queue.append(nxt)

    return html.Div([
        html.P(f"Connected Sources: {len(sources)}"),
        html.P(f"Connected Sinks: {len(sinks)}"),
        html.P("Path highlighting shown in graph.")
    ])


# Add graph statistics
@app.callback(
    Output("graph-stats", "children"),
    Input("graph-data-store", "data")
)
def display_graph_stats(graph_data):
    """Render a div with the graph statistics given the graph_data"""
    if not graph_data:
        return "No data loaded"

    # Get the nodes and edges
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Calculate the number of sources and sinks
    num_sources = sum(1 for n in nodes if n.get("type") == "source")
    num_sinks = sum(1 for n in nodes if n.get("type") == "sink")

    return html.Div([
        html.P(f"Total Nodes: {len(nodes)}"),
        html.P(f"Total Edges: {len(edges)}"),
        html.P(f"Sources: {num_sources}"),
        html.P(f"Sinks: {num_sinks}")
    ])


# Load JSON graph into Store based on which graph the user selects
@app.callback(
    Output("graph-data-store", "data"),
    Input("graph-selector", "value")
)
def load_graph(selected_name):
    if not selected_name:
        return None
    
    graph_path = GRAPH_DIR / f"{selected_name}_graph.json"

    if not graph_path.exists():
        return None
    
    # Open the graph JSON file, and return it's contents as a JSON object
    with open(graph_path, "r") as f:
        return json.load(f)


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
    Input("selected-node", "data"),
    Input("simplify-toggle", "value") # Determine if intermediate nodes should be hidden
)
def build_elements(graph_data, selected_node, simplify_mode):
    if not graph_data:
        return []
    
    simplify = "simplify" in (simplify_mode or [])
    
    if simplify:
        """Sink -> Source Only Button Selected - Rewrite graph_data"""
        # Build adjacency
        adj_forward = {}
        for edge in graph_data["edges"]:
            src = safe_id(edge["from"])
            tgt = safe_id(edge["to"])
            adj_forward.setdefault(src, []).append(tgt)

        # Identify sources and sinks
        sources = []
        sinks = set()
        node_map = {}

        for node in graph_data["nodes"]:
            sid = safe_id(node["id"])
            node_map[sid] = node
            if node.get("type") == "source":
                sources.append(sid)
            if node.get("type") == "sink":
                sinks.add(sid)

        # Find all source → sink reachability
        new_edges = set()

        for src in sources:
            queue = deque([src])
            visited = set()

            while queue:
                curr = queue.popleft()
                if curr in visited:
                    continue
                visited.add(curr)

                if curr in sinks and curr != src:
                    new_edges.add((src, curr))

                for nxt in adj_forward.get(curr, []):
                    queue.append(nxt)

        # Replace graph with simplified version
        simplified_nodes = [
            node for node in graph_data["nodes"]
            if node.get("type") in {"source", "sink"}
        ]

        graph_data = {
            "nodes": simplified_nodes,
            "edges": [{"from": s, "to": t} for s, t in new_edges]
        }

    """Rebuild the elements"""
    # Add a catch to block useless nodes from being added to the graph
    USELESS_LABELS = {"append", "toString", "onResume"}

    filtered_nodes = []
    for node in graph_data.get("nodes", []):
        label = node.get("label", "")
        if not simplify:
            # Only append intermediate nodes if "simplify" not checked
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

    return elements


# Node click info
@app.callback(
    Output("node-data", "children"),
    Input("taint-graph", "tapNodeData")
)
def display_node_info(node_data):
    """Display the information of a node when it's clicked"""
    if not node_data:
        return html.Div("Click a node to see details.")

    children = [
        html.H4(node_data.get("label", "Unknown")),
        html.P([
            html.B("Type: "), node_data.get("type", "unknown")
        ]),
        html.P([
            html.B("Class: "), node_data.get("class", "N/A")
        ]),
        html.P([
            html.B("Method: "), node_data.get("method", "N/A")
        ]),
    ]

    # Only show line if it's actually present (i.e. not None)
    if node_data.get("line") is not None:
        children.append(
            html.P([
                html.B("Line: "), str(node_data["line"])
            ])
        )

    children.extend([
        html.H5("Code"),
        html.Pre(node_data.get("code") or "N/A", style={
            "background": "#f4f4f4",
            "padding": "10px"
        }),
        html.H5("Raw IR"),
        html.Pre(node_data.get("raw") or "N/A", style={
            "background": "#eee",
            "padding": "10px",
            "fontSize": "12px"
        })
    ])

    return html.Div(children)


# Run app
if __name__ == "__main__":
    app.run(debug=True)