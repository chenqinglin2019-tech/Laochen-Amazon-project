"""r6 (report-always-v1): a new task always ends with a report.

Run B0GFNWR8FW (2026-10-15, eyeliner stamp pen) reviewed every candidate in both chains - both rated design
USD959051S1 高 - and still published nothing: one module answer cited the patent's own Google page and drawing, the
binding list did not count them, the retry re-sent the same prompt and there was no fallback. Every product that reached
the final review in the owner's runs hit at least one such stop. New tasks carry this marker; under it:

* one evidence set per candidate (candidate_evidence.py) is used by the review packet, the module check and publication;
* a module answer is repaired deterministically and only unusable rows become pending (module_repair.py);
* a module that cannot be obtained becomes pending rows of that chain, the chain summary is written by the program,
  the review has a deadline inside the 40-minute run, and the chief settles single-review rows at checkpoint 3;
* the pipeline degrades instead of stopping where the program can act (run_pipeline.py).

Tasks without the marker keep their exact behaviour.
"""
REVISION = 'report-always-v1'
TASK_FIELD = 'stability_revision'
# The whole run, in machine seconds, that the review deadline is fitted into (owner: at most 40 minutes).
RUN_SECONDS = 2400
# Room left after the review for adjudication and publication.
PUBLISH_RESERVE_SECONDS = 150
# One review session never runs longer than this on a marked task.
SESSION_SECONDS = 600


def enabled(task):
    return isinstance(task, dict) and task.get(TASK_FIELD) == REVISION
