Purpose of each file:

data/xml_results/*.xml
    - store FlowDroid XML outputs

src/run_flowdroid.py
    - used to run FlowDroid and save the XML results file

src/parser/xml_parser.py
    - parses FlowDroid XML -> structured Python dict

src/graph/graph_builder.py
    - takes parsed dict -> builds NetworkX graph -> exports JSON

src/graph/graph_dashboard.py
    - front-end file for the dashboard

src/utils/file_io.py
    - optional helpers: read log, write JSON files, path handling

outputs/graphs/*.json
    - exported graph data for visualization dashboard

tests/test_parser.py
    - test our parser and graph builder against sample logs

requirements.txt
    - track all Python packages we use