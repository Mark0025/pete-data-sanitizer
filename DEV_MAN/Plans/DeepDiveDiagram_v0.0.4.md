## Plan: Deep-dive runtime diagram (v0.0.4)

### Goal
Add a **deep-dive runtime diagram** that helps agents debug “what’s working vs not” by showing:

- pipeline steps (runtime, not static parsing)
- key metrics (match rate, seller coverage, missing sellers)
- small samples (e.g., first N addresses missing sellers / not matching contacts)

This should not break the existing pipeline or existing reports.

### Current state (v0.0.3)
- `build` produces:
  - import XLSX/CSV
  - reports (json/md/csvs)
  - runtime run record: `uploads/runs/<run_id>.json` + `.summary.md` + `.log`
  - runtime diagram: `uploads/flowcharts/acki_run_<run_id>.flow.txt` + `.summary.md`
- `build --debug-report` produces:
  - `uploads/runs/<run_id>.debug.md` + `.debug.json`

### What we will add (v0.0.4)
When `--debug-report` is enabled:

- Generate an additional diagram pair:
  - `uploads/flowcharts/acki_run_<run_id>.deep.flow.txt`
  - `uploads/flowcharts/acki_run_<run_id>.deep.summary.md`

The deep diagram should be **derived from runtime + debug metrics**, not from raw Python code parsing.

### Implementation steps
1. **Versioning**
   - bump version to `0.0.4`
   - add `CHANGELOG.md` entry

2. **Deep-dive diagram generator**
   - build flowchart.js text with additional nodes/annotations for:
     - address match rate
     - seller coverage (Seller/Seller2/Seller3)
     - missing-seller count + sample
     - contact collision highlights sample
   - keep output stable and small (cap sample sizes)

3. **Wire into build**
   - only generate deep diagram when `--debug-report` is used (so normal runs stay fast/simple)
   - store deep diagram paths in run outputs when created

4. **Server/index**
   - index should link:
     - latest summary
     - latest debug
     - latest runtime diagram
     - latest deep diagram (if exists)

5. **Smoke test**
   - run `build --debug-report`
   - verify new deep diagram files exist
   - verify server renders `/diagram/acki_run_<run_id>.deep`

### Non-goals (for this version)
- Full “every function call” tracing as a default (still learning mode).
- PNG/SVG rendering on disk (browser rendering is sufficient for MVP).
- Aggressive disk cleanup/retention (can be added later).

