"""Local shopfloor topology + test-record graph for the SOHU rack.

Mirror ``pega-sfis`` and EOS to local disk, then render one YAML per top-level
serial: the full part-SN tree with every part's test history attached, and an
explicit verdict on which parts *can* have one.

Read ``README.md`` for the why and ``docs/JOIN.md`` for the source-to-source
join. ``graph.py`` is the module to read first.
"""

__all__ = ["config", "sfis", "eos", "graph", "mirror", "render", "stations"]
