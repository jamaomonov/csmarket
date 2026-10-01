# apps/scheduler

APScheduler in its own container. Jobs live in `src/csmarket_scheduler/jobs/`, each calling a module's service functions directly — the scheduler does **no** business work, only timing. Register in `main.build_scheduler`; long-period jobs take `startup.first_run_after(n)` with a stagger ≥ 15 s between them. Run: `make dev-scheduler`.
