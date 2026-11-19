# Working on this repository

- Read README.md and PROJECT.md before implementing new features.
- Explain substantive changes with a runnable command and a short code walkthrough.
- Verify GRID schema fields and account access before treating them as available.
- Keep credentials in environment variables or ignored .env files. Never print keys.
- Keep raw API responses, schemas and derived datasets under ignored data/ or artifacts/.
- Preserve series/game distinctions and explicit missing values.
- Mark synthetic fixtures and Loopfeed data as test data.
- Do not infer historical trajectories from final aggregates.
- Run `python3 -m unittest discover -s tests -v` after client or ingestion changes.
