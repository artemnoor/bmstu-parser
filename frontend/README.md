# University Data Console

Static frontend for the University Data Platform API. The client keeps the
selected university in local storage, shows declared capabilities and calls
only university-scoped endpoints. It does not access `data/` or backend
implementation modules.

Run it with `python -m http.server 5173 --directory frontend` after starting
`university-api`, or serve the directory through the included nginx container.
