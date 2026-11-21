# Follow the Rupee: web app

The front end for the Team 6 project. It shows where each Mumbai ward's monsoon road repair money went, whether the work held up, and where the next rupee should go. All data is synthetic and every contractor is fictional.

Stack: Vite + React + Tailwind CSS v4 + daisyUI 5, with recharts for charts and d3-geo for the ward map. There is no backend. The app reads JSON files that `export_data.py` builds from the SQLite database (`outputs/follow_the_rupee.db`), so it makes no live Claude calls and works offline. The JSON is re-exported automatically every time the database rebuilds (any pipeline run), and `public/data/manifest.json` records which database build it came from.

## Pages

| Route | Page | What it answers |
|---|---|---|
| `#/` | Overview | City totals, ward map, where the flagged money is |
| `#/wards/F%2FS` | Ward money trail | One ward: budget vs billed, spend by contractor and method, summaries |
| `#/flags?type=OVERBILL` | Audit flags | Filterable worklist of every flag, with CSV download |
| `#/contractors/CT05` | Contractors | Fair, method-adjusted scorecards and fairness notes |
| `#/plan/F%2FS` | Next rupee | Ranked repair plan per ward, sized to the remaining budget |
| `#/track/BMC25-000005` | Complaint tracker | What happened to one complaint, in any language |

Any work order ID opens a drill-down panel showing the complaints behind it, the road, the contractor, every audit flag with its evidence, and links to related jobs. The top search bar jumps straight to a work order, complaint or ward.

## Run it locally

You need Node.js 20 or newer (`node --version` to check) and the project's Python venv.

1. Open Git Bash or PowerShell in the repo root.
2. Refresh the data (only needed after the pipeline outputs change):
   ```bash
   .venv/Scripts/python app/export_data.py
   ```
3. Install the app's packages (first time only):
   ```bash
   cd app
   npm install
   ```
4. Start the dev server, then open the address it prints (usually http://localhost:5173):
   ```bash
   npm run dev
   ```

## Build for deployment

```bash
cd app
npm run build
```

This writes a static site to `app/dist/`. Upload that folder to any static host (Vercel, Netlify, GitHub Pages). It uses relative paths and hash routes, so no server configuration is needed.

## Where things live

| Path | What |
|---|---|
| `export_data.py` | Turns the database (`outputs/follow_the_rupee.db`, read through `pipeline.db`) into `public/data/*.json`. It never reads parquet or CSV files |
| `src/lib/` | Data loading, Indian rupee formatting, hash router |
| `src/components/` | App shell, ward map, work-order drill-down, shared UI pieces |
| `src/pages/` | One file per page |
| `src/index.css` | daisyUI light and dark themes (`rupee`, `rupee-dark`) and design tokens |

Design rules: one accent colour (teal), colours only from the theme, cards 12px radius, buttons and inputs 8px, badges pill. Neutral wording ("needs review"), and every number comes from the pipeline.
