from celery import Celery
import yaml
from worker import process_url

app = Celery("scheduler", broker="redis://localhost:6379/0")


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Every 10 minutes
    sender.add_periodic_task(600, scan_docs.s())


@app.task
def scan_docs():
    with open("docs.yaml") as f:
        data = yaml.safe_load(f)

    urls = data.get("urls", [])

    for url in urls:
        process_url.delay(url)

    return f"Queued {len(urls)} URLs"
