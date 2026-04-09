from dash import Dash, html
import dash_cytoscape as cyto

app = Dash()

app.layout = html.Div([
    cyto.Cytoscape(
        id='cytoscape-two-nodes',
        layout={'name': 'preset'},
        style={'width': '100%', 'height': '400px'},
        elements=[
            {'data': {'id': 'getLongitude', 'label': 'getLongitude'}},
            {'data': {'id': 'tostring', 'label': 'tostring'}},
            {'data': {'source': 'getLongitude', 'target': 'tostring'}}
        ]
    )
])

if __name__ == '__main__':
    app.run(debug=True)
