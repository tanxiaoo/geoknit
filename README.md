# GeoKnit

Local, open-source visual programming for geospatial analysis, in the style of
Grasshopper for Rhino. Components are small Python scripts with typed inputs
and outputs, wired together on a browser canvas served by a local Python
backend.

**Status: pre-alpha.** Nothing usable yet; see [PLAN.md](PLAN.md) for progress
and [docs/SPEC.md](docs/SPEC.md) for the design.

## Install (development)

```bash
pip install -e ".[dev]"
geoknit --version

cd frontend
npm install
npm run dev
```

## License

Apache-2.0, see [LICENSE](LICENSE).
