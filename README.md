# MTGLib

MTGLib is a local Magic: The Gathering card corpus stored as plain Markdown, plus a lightweight app layer for browsing the corpus and experimenting with deck generation against it.

## What It Is

The repository centers on a checked-in `cards/` directory where each card is represented as a human-readable Markdown document with a stable structure. That corpus is paired with a small FastAPI backend and frontend so the data can be explored locally without needing a database or external service.

## Why It Exists

The project exists to keep MTG card data easy to read, version, diff, and parse. Markdown is the source of truth, which makes the corpus useful both for humans editing it directly and for tools that want a predictable local dataset for search, indexing, analysis, or deck-building experiments.

## Get Started

From the `mtglib/` folder, run:

```powershell
.\start.cmd
```

That launcher will:

- create a local Python environment if needed
- install backend and frontend dependencies
- build the frontend when needed
- start the app at `http://127.0.0.1:8000/`

Requirements:

- Python 3 on `PATH`
- Node.js and `npm` on `PATH`
- `git` is optional and only used for update checks

If you only want to prepare the app without launching it:

```powershell
.\start.cmd -SetupOnly
```