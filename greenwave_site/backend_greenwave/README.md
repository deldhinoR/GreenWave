# Traffic Map Project

This small demo lets a user select an area of OpenStreetMap, convert the
selected roads into a SUMO network, edit lane counts in the browser and
(re)generate a simulation.

## Workflow

1. Run the Flask server:
   ```powershell
   cd c:\Users\mzeyn\Desktop\traffic-map-project
   python app.py
   ```

2. Open `index.html` in your browser (e.g. `http://127.0.0.1:5000/index.html` if
   you serve static files via Flask or just open the file directly). A full
   screen OSM map is shown.

3. Draw a **rectangle** with the draw controls. When you finish drawing, the
   bounding box will be sent to the server and saved in `window.selectedBounds`.

4. Click the **Simulate** button once the red OSM ways have been rendered; the
   button only becomes active after a successful geometry fetch. The page will
   redirect to `netedit.html` and the server will fetch and convert the selected
   area to a SUMO network.

5. **NetEdit page features:**
   * **Click a link** to open a context menu with four options:
     - *Change lanes* modifies the total lane count for the entire segment.
     - *Add lane from here* splits the segment at the click point and adds the
       specified number of lanes to the downstream piece. This mimics SUMO's
       ability to add lanes mid‑link.
     - *Add lane (drag)* drops a draggable handle at the clicked location. Move
       it along the road to choose where the widened section ends, then release
       and specify the lane increase. This provides a rudimentary drag‑and‑drop
       workflow.
     - *Turn restrictions* shows other links that depart from the end node;
       you can toggle whether turns onto each are allowed. Restrictions are
       stored per-segment and shown in the tooltip along with the lane count.
   * Segments may be split, creating two new polylines with derived IDs (original
     ID suffixed with `_a`/`_b`).
   * When you press **Save edits**, all modifications including lane splits and
     turn restrictions are sent back to the server in the JSON payload. The
     backend prints them to the console and also writes `last_mods.json` so you
     can examine exactly what was submitted.
   * **Back** returns to the drawing map so you can choose a different area.

6. Use **Back** to return to the original map and draw a new area if desired.

## Development notes

* `app.py` exposes the following endpoints:
  * `/get_osm_area` – returns raw Overpass JSON (used by the first page).
  * `/get_sumo_network` – converts the bounding box to SUMO and returns
    simplified link data (`coords`, `lanes`, `id`).
  * `/update_network` – accepts a list of lane-count changes; this demo simply
    echoes them but could write them back to a `.net.xml` file or trigger a
    rerun of `netconvert`.

* `netedit.html` + `netedit.js` implement the lightweight editor.  The
  front‑end stores the bounding box in `localStorage` and reads it on the
  editor page.

* `sumolib` (Python bindings for SUMO) is optionally used to parse the
  generated `.net.xml` more conveniently; otherwise the code falls back on
  manual XML parsing. To install it:
  ```powershell
  pip install sumolib
  ```
  ; you also need SUMO itself on your PATH so that the `netconvert` binary can
  be executed. See [SUMO installation instructions](https://sumo.dlr.de/) for
  your platform.

* The static files are not currently served by Flask – the easiest way to use
  the demo is to open `index.html` directly in a browser and make sure the
  server is running at `http://127.0.0.1:5000` so that the XHR requests work.
  You can also add `app = Flask(__name__, static_folder='.', static_url_path='')`
  if you prefer to serve them via Flask.

## Future improvements

* Integrate the actual SUMO simulator (`sumo` or `sumo-gui`) to run traffic
  after the network is finalised.
* Add the ability to drag nodes, split/merge edges, add new links, etc. – a
  miniature NetEdit clone in the browser as requested.
* Persist edited networks to disk or a database so they can be reloaded.
* Provide visual feedback if `netconvert` fails (currently the backend prints
  a message and returns the fallback geometry).

---

This README is a starting point; adapt it to your needs.
