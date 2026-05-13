from pathlib import Path
import json
import sys
from dash import Dash, html, dcc, Output, Input, callback_context, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import base64
import dash_cytoscape as cyto
from collections import deque

# Paths for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src"))

from run_flowdroid import run_flowdroid
from graph.graph_builder import build_graph, export_json
from parser.xml_parser import parse_flowdroid_xml


# Discover the available graphs in "outputs/graphs"
GRAPH_DIR = PROJECT_ROOT / "outputs/graphs"
def get_available_graphs():
    """Search "outputs/graphs" and find all {name}_graph.json files as viable graphs to display"""
    graph_options = []
    for f in GRAPH_DIR.glob("*_graph.json"):
        graph_options.append(f.stem.replace("_graph", ""))
    return sorted(graph_options)


# Make a JS-safe ID (some of these markers will trigger weird behavior - I found out while trying to use "toString" as a node name)
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

# App styling and Javascript script for the "Expand"/"Exit" button! (global css animation)
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>T-Flow</title>
        {%favicon%}
        {%css%}

        <style>

            html, body {
                margin: 0;
                padding: 0;
                height: 100%;
                width: 100%;
                background: #020617;
                overflow: hidden;
            }

            @keyframes pulseBG {
                0% { filter: brightness(1); }
                50% { filter: brightness(1.15); }
                100% { filter: brightness(1); }
            }

            @keyframes floatGlow {
                0% { transform: translateY(0px); }
                50% { transform: translateY(-6px); }
                100% { transform: translateY(0px); }
            }

            @keyframes nodePulse {
                0% { box-shadow: 0 0 5px rgba(56,189,248,0.2); }
                50% { box-shadow: 0 0 18px rgba(56,189,248,0.6); }
                100% { box-shadow: 0 0 5px rgba(56,189,248,0.2); }
            }

            body {
                margin: 0;
                overflow-x: auto;
                overflow-y: auto;
                background: transparent;
            }

        </style>

        // This is our main script to handle the "Expand" and "Exit" features for our graph! :)
        <script>
            // Use event delegation on the document so we catch the click even after Dash/React re-renders the button
            let isFullscreen = false;

            document.addEventListener('click', function(e) {
                // Only fire if the clicked element is our expand button
                if (!e.target || e.target.id !== 'fullscreen-btn') return;

                const graphPanel = document.getElementById('graph-panel');
                const rightPanel = document.getElementById('right-panel');
                const header     = document.getElementById('header-section');
                const desc       = document.getElementById('desc-section');

                isFullscreen = !isFullscreen;

                if (isFullscreen) {
                    // Expand the graph to fill the screen
                    e.target.innerText            = 'Exit';
                    graphPanel.style.position     = 'fixed';
                    graphPanel.style.top          = '0';
                    graphPanel.style.left         = '0';
                    graphPanel.style.width        = '100vw';
                    graphPanel.style.height       = '100vh';
                    graphPanel.style.zIndex       = '9999';
                    graphPanel.style.borderRadius = '0';
                    if (rightPanel) rightPanel.style.display = 'none';
                    if (header)     header.style.display     = 'none';
                    if (desc)       desc.style.display       = 'none';
                } else {
                    // Collapse the graph back to it's normal size
                    e.target.innerText            = 'Expand Graph';
                    graphPanel.style.position     = '';
                    graphPanel.style.top          = '';
                    graphPanel.style.left         = '';
                    graphPanel.style.width        = '';
                    graphPanel.style.height       = '';
                    graphPanel.style.zIndex       = '';
                    graphPanel.style.borderRadius = '10px';
                    if (rightPanel) rightPanel.style.display = '';
                    if (header)     header.style.display     = '';
                    if (desc)       desc.style.display       = '';
                }

                // After the resize, find the Cytoscape instance on the DOM element and call resize() + fit() directly so nodes reflow to the new container size and look nice!
                setTimeout(function() {
                    // Dash Cytoscape attaches the cy instance to the container div's _cyreg property
                    const cyDiv = document.getElementById('taint-graph');
                    if (!cyDiv) return;

                    // Walk through all of the child elements to find the one with the cy instance attached
                    const findCy = (el) => {
                        if (el._cyreg && el._cyreg.cy) return el._cyreg.cy;
                        for (let child of el.children) {
                            const found = findCy(child);
                            if (found) return found;
                        }
                        return null;
                    };

                    const cy = findCy(cyDiv);
                    // If the cyDiv has been found, the resize and fit it!
                    if (cy) {
                        cy.resize();  // Just means to tell Cytoscape the containers changed size
                        cy.fit();     // Re-center and scale all elements to fill it
                    }
                }, 200);
            });
        </script>

    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''


app.layout = html.Div([

    dcc.Location(id="url", refresh=False),
    dcc.Store(id="graph-data-store"),
    dcc.Store(id="selected-node"),

    html.Div([

        # HEADER
        html.Div([
            html.H1("T-Flow: Taint Flow Explorer",
                style={
                    "color": "#E0F2FE",
                    "letterSpacing": "4px",
                    "textShadow": "0 0 20px rgba(56,189,248,0.6)",
                    "animation": "floatGlow 4s ease-in-out infinite"
                },
            ),

            html.Div("Interactive visualization of how data moves through programs",
                     style={"color": "#94A3B8"})
        ], style={"marginBottom": "12px"}, id="header-section"),

        # Description of our app
        html.Div([
            html.H4("What is T-Flow?", style={"color": "#E0F2FE", "marginBottom": "5px"}),

            html.P(
                "T-Flow visualizes how sensitive data moves through a program. "
                "It converts static taint analysis output into an interactive graph "
                "so you can explore how data flows from sources (like user input or device info) "
                "to sinks (like network or file output).",
                style={"color": "#94A3B8", "fontSize": "12px", "lineHeight": "1.4"}
            ),

            html.P(
                "Click nodes to inspect code, trace paths, and identify potential data leaks.",
                style={"color": "#94A3B8", "fontSize": "12px"}
            ),

        ], style={
            "color": "#94A3B8",
            "marginBottom": "10px",
            "paddingleft": "4px",
            "border": "1px solid rgba(56,189,248,0.2)",
            "borderRadius": "8px",
            "background": "rgba(2,6,23,0.4)"
        }, id="desc-section"),

        # MAIN CONTENT
        html.Div([

            # LEFT PANEL
            html.Div([

                html.Div([
                    dcc.Checklist(
                        id="simplify-toggle",
                        options=[
                            {
                                "label": " Filter Intermediate Nodes (Source -> Sink)",
                                "value": "simplify"
                            }
                        ],
                        value=[],
                        labelStyle={
                            "color": "#BAE6FD",
                            "fontSize": "11px",
                            "display": "inline-block",
                            "cursor": "pointer"
                        },
                        inputStyle={
                            "marginRight": "6px"
                        }
                    )
                ]),

                dcc.Upload(
                    id="upload-apk",
                    children=html.Button("Select an .apk to analyze",
                        style={
                            "backgroundColor": "#0EA5E9",
                            "color": "black",
                            "border": "none",
                            "padding": "4px 8px",
                            "fontSize": "11px"
                        }),
                    multiple=False,
                    style={"marginBottom": "4px"}
                ),

                html.Div(id="upload-status", style={"color": "#A5F3FC"}),

                html.Div([
                    # Select a graph
                    dcc.Dropdown(
                        id="graph-selector",
                        placeholder="Graph",
                        style={"fontSize": "11px", "flex": 1}
                    ),
                    # Delete a graph
                    html.Button(
                        "Del",
                        id="delete-graph-btn",
                        style={
                            "backgroundColor": "#EF4444",
                            "color": "white",
                            "border": "none",
                            "padding": "4px 8px",
                            "fontSize": "11px"
                        }
                    )
                ], style={
                    "display": "flex",
                    "gap": "6px",
                    "alignItems": "center"
                }),

                # Fullscreen toggle button
                html.Div([
                    html.H3("Flow Map", style={"color": "#E0F2FE", "margin": 0}),
                    html.Button(
                        "Expand Graph",
                        id="fullscreen-btn",
                        style={
                            "backgroundColor": "transparent",
                            "color": "#38BDF8",
                            "border": "1px solid #38BDF8",
                            "padding": "3px 10px",
                            "fontSize": "11px",
                            "cursor": "pointer",
                            "borderRadius": "4px",
                            "letterSpacing": "1px"
                        }
                    )
                ], style={
                    "padding": "10px",
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center"
                }),



                cyto.Cytoscape(
                    id="taint-graph",
                    layout={
                        "name": "breadthfirst",
                        "directed": True,
                        "orientation": "horizontal",
                        "spacingFactor": 1,
                        "padding": 10,
                        "roots": '[type = "source"]',
                        "animate": False
                    },
                    style={
                        "flex": "1 1 auto",
                        "width": "100%",
                        "minHeight": 0,
                        "height": "100%",
                        "backgroundColor": "#020617",
                        "border": "1px solid rgba(56,189,248,0.2)",
                        "boxShadow": "0 0 40px rgba(56,189,248,0.1)",
                        "animation": "nodePulse 6s ease-in-out infinite",
                    },
                    elements=[],
                    stylesheet=[
                        {"selector": "node", "style": {
                            "label": "data(label)",
                            "color": "#E0F2FE",
                            "font-size": "10px",
                            "text-outline-width": 2,
                            "text-outline-color": "#020617",
                            "background-opacity": 0.9,
                            "border-width": 2,
                            "border-color": "#38BDF8",
                            "transition-property": "background-color, border-color, box-shadow",
                            "transition-duration": "0.3s",
                            "width": 18,
                            "height": 18
                        }},
                        {"selector": ".source", "style": {"background-color": "#38BDF8"}},
                        {"selector": ".sink", "style": {"background-color": "#F97316"}},
                        {"selector": ".intermediate", "style": {"background-color": "#64748B"}},
                        {"selector": "edge", "style": {
                            "line-color": "#38BDF8",
                            "target-arrow-color": "#F97316",
                            "width": 1.5,
                            "curve-style": "bezier",
                            "opacity": 0.5
                        }},
                        {"selector": ".highlighted", "style": {
                            "border-width": 3,
                            "border-color": "#F97316",
                            "shadow-blur": 25,
                            "shadow-color": "#38BDF8",
                            "shadow-opacity": 0.9,
                            "animation": "nodePulse 1.8s infinite"
                        }},
                    ]
                ),

                # Legend to describe the graph
                html.Div([
                    html.H4("Legend", style={"color": "#E0F2FE", "marginTop": "10px"}),

                    html.P("Source: entry point of data (e.g., user input, device info)",
                        style={"color": "#38BDF8", "fontSize": "11px"}),

                    html.P("Intermediate: transformed or propagated data",
                        style={"color": "#94A3B8", "fontSize": "11px"}),

                    html.P("Sink: sensitive destination (network, file, etc.)",
                        style={"color": "#F97316", "fontSize": "11px"}),

                    html.P("Highlighted: nodes involved in selected path",
                        style={"color": "#E0F2FE", "fontSize": "11px"}),
                ], style={
                    "marginTop": "10px",
                    "padding": "8px",
                    "borderTop": "1px solid rgba(56,189,248,0.2)"
                }),

            ], style={
                "flex": 4,
                "minWidth": 0,
                "display": "flex",
                "flexDirection": "column",
                "overflow": "hidden",
                "gap": "6px",
                "padding": "8px",
                "background": "rgba(17,24,39,0.4)",
                "backdropFilter": "blur(10px)",
                "border": "1px solid rgba(56,189,248,0.15)",
                "borderRadius": "10px",
                "boxShadow": "0 0 30px rgba(56,189,248,0.08)"
                }, id="graph-panel"
            ),

            # RIGHT PANEL
            html.Div([

                html.Div([
                    html.H3("Node Data", style={"color": "#E0F2FE"}),
                    html.Div(id="node-data"),

                    html.H3("Traversal Path", style={"color": "#E0F2FE"}),
                    html.Div(id="path-data", style={"color": "white"}),

                    html.H3("System Stats", style={"color": "#E0F2FE"}),
                    html.Div(id="graph-stats", style={"color": "white"})

                ], style={
                    "flex": 1,
                    "overflowY": "auto",
                    "paddingRight": "6px",
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "10px",
                    "minHeight": 0
                })

            ], style={
                    "flex": 1,
                    "minWidth": 0,
                    "display": "flex",
                    "flexDirection": "column",
                    "overflow": "hidden",
                    "padding": "10px",
                    "background": "rgba(2,6,23,0.6)",
                    "backdropFilter": "blur(12px)",
                    "border": "1px solid rgba(249,115,22,0.12)",
                    "borderRadius": "10px",
                    "boxShadow": "0 0 30px rgba(249,115,22,0.05)"
                }, id="right-panel"
            )

        ], style={
            "display": "flex",
            "flex": 1,
            "gap": "12px",
            "minHeight": 0,
            "minWidth": 0,
            "width": "100%"
        })

    ], style={
        "position": "relative",
        "zIndex": 10,
        "height": "100vh",
        "width": "100vw",
        "display": "flex",
        "flexDirection": "column",
        "padding": "16px",
        "boxSizing": "border-box",
        "flexDirection": "column",
        "fontFamily": "monospace",
        "background": "transparent",
        "animation": "pulseBG 12s ease-in-out infinite"
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
        return html.Pre("Click a node to see its full path.", style={"color": "white"})

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


# Callback that manages graph state:
#   1) Refreshes the graph
#   2) Delete graphs
#   3) Handle .apk file uploads and graph creation
@app.callback(
    Output("graph-selector", "options"),
    Output("graph-selector", "value"),
    Output("upload-status", "children"),
    Input("url", "pathname"),
    Input("delete-graph-btn", "n_clicks"),
    Input("upload-apk", "contents"),
    State("graph-selector", "value"),
    State("upload-apk", "filename"),
    prevent_initial_call=False
)
def manage_graphs(pathname, delete_clicks, upload_contents,
                  selected_graph, upload_filename):

    ctx = callback_context

    if not ctx.triggered:
        trigger = "initial"
    else:
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

    # -------------------------
    # INITIAL PAGE LOAD (load the top graph)
    # -------------------------
    if trigger in ["url", "initial"]:
        graphs = get_available_graphs()

        options = [{"label": g, "value": g} for g in graphs]
        value = graphs[0] if graphs else None

        return options, value, "Ready."

    # -------------------------
    # DELETE GRAPH (remove the graph JSON so it doesn't load with the "available graphs")
    # -------------------------
    elif trigger == "delete-graph-btn":

        if selected_graph:
            graph_file = GRAPH_DIR / f"{selected_graph}_graph.json"

            if graph_file.exists():
                graph_file.unlink()

        graphs = get_available_graphs()

        options = [{"label": g, "value": g} for g in graphs]
        value = graphs[0] if graphs else None

        return options, value, f"Deleted graph: {selected_graph}"

    # -------------------------
    # UPLOAD APK (have FlowDroid run on .apk and do full pipeline)
    # -------------------------
    elif trigger == "upload-apk":

        if upload_contents is None:
            raise PreventUpdate

        try:
            content_type, content_string = upload_contents.split(',')
            decoded = base64.b64decode(content_string)

            upload_dir = PROJECT_ROOT / "data/uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)

            upload_path = upload_dir / upload_filename

            with open(upload_path, "wb") as f:
                f.write(decoded)

            apk_name = Path(upload_filename).stem

            # Run FlowDroid
            run_flowdroid(upload_path)

            # Parse XML
            xml_path = PROJECT_ROOT / "data/xml_results" / f"{apk_name}.xml"
            parsed_data = parse_flowdroid_xml(xml_path)

            # Build Graph
            G = build_graph(parsed_data)

            output_dir = PROJECT_ROOT / "outputs/graphs"
            output_dir.mkdir(parents=True, exist_ok=True)

            graph_output = output_dir / f"{apk_name}_graph.json"
            export_json(G, graph_output)
            graphs = get_available_graphs()
            options = [{"label": g, "value": g} for g in graphs]

            return (
                options,
                apk_name,
                f"Upload complete: {apk_name}"
            )

        except Exception as e:
            graphs = get_available_graphs()
            options = [{"label": g, "value": g} for g in graphs]
            return (
                options,
                selected_graph,
                f"Upload failed: {str(e)}"
            )

    return no_update, no_update, no_update


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

        # Find all source -> sink reachability (i.e. nodes you can get to from the current one)
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
        return html.Div("Click a node to see details.", style={"color": "white"})

    children = [
        html.H4(node_data.get("label", "Unknown"), style={"color": "white"}),
        html.P([
            html.B("Type: "), node_data.get("type", "unknown")
        ], style={"color": "white"}),
        html.P([
            html.B("Class: "), node_data.get("class", "N/A")
        ], style={"color": "white"}),
        html.P([
            html.B("Method: "), node_data.get("method", "N/A")
        ], style={"color": "white"}),
    ]

    # Only show line if it's actually present (i.e. not None)
    if node_data.get("line") is not None:
        children.append(
            html.P([
                html.B("Line: "), str(node_data["line"])
            ], style={"color": "white"})
        )

    children.extend([
        html.H5("Code", style={"color": "white"}),
        html.Pre(node_data.get("code") or "N/A", style={
            "color": "black",
            "background": "#f4f4f4",
            "padding": "10px",
            "fontSize": "12px",
            "whiteSpace": "pre-wrap",
            "wordBreak": "break-word",
            "overflowWrap": "anywhere",
            "maxWidth": "100%",
            "overflowX": "auto",
            "borderRadius": "6px"
        }),
        html.H5("Raw IR", style={"color": "white"}),
        html.Pre(node_data.get("raw") or "N/A", style={
            "color": "black",
            "background": "#eee",
            "padding": "10px",
            "fontSize": "12px",
            "whiteSpace": "pre-wrap",
            "wordBreak": "break-word",
            "overflowWrap": "anywhere",
            "maxWidth": "100%",
            "overflowX": "auto",
            "borderRadius": "6px"
        })
    ])

    return html.Div(children)


# Run app
if __name__ == "__main__":
    app.run(debug=True)