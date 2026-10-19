# Offline geographic basemap

Made with Natural Earth. Natural Earth geographic vector data is public domain.

- Provider and licence: https://www.naturalearthdata.com/about/terms-of-use/
- World boundary source: https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/ (1:110 million)
- Korean peninsula boundary source: https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/ (1:50 million)
- City representative points: https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-populated-places/ (1:10 million populated places)
- Maintainer repository commit: `ca96624a56bd078437bca8184e78163e5039ad19`
- Exact source URLs, downloaded byte hashes and derived hashes: [source_manifest.json](source_manifest.json)

`world.geojson` and `korea.geojson` retain the source polygon geometry with coordinates rounded to four decimal places and only display properties. `positions.json` retains Natural Earth's cartographic country label points and selected named populated-place points, with source feature IDs. Korean name aliases only translate city names; their coordinates come from those source records.

Country/city representative points show an approximate regional location, never a verified data-center parcel. Unknown cities remain unlocated when no packaged reference point is available. No company headquarters or publisher country is used to infer a project location. Boundaries are generalized cartographic data, not cadastral surveys or a determination of territorial claims. The map makes no external tile, CDN or runtime geocoding requests.
