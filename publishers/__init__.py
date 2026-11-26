"""Publisher registry. Add a publisher by dropping a module here with
`publish(records, out)` and listing it below. The gate (gate.py) is shared and not optional."""
from . import static_site

PUBLISHERS = {"static-site": static_site}
