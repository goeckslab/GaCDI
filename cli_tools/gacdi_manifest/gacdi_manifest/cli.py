"""CLI: ``gacdi-manifest gdc [...]`` — build GDC manifests + enriched metadata."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import cbioportal, enrich, gdc, io, version_string
from .errors import InputError, ManifestError
from .filters import build_filters
from .join import join
from .net import build_session

log = logging.getLogger("gacdi_manifest")

# Facets summarised in count-only previews.
PREVIEW_FACETS = [
    "data_category",
    "data_type",
    "experimental_strategy",
    "data_format",
    "platform",
    "access",
    "cases.primary_site",
    "analysis.workflow_type",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gacdi-manifest", description="GaCDI manifest builder.")
    parser.add_argument("--version", action="version", version=f"gacdi-manifest {version_string()}")
    sub = parser.add_subparsers(dest="database", required=True, metavar="DATABASE")

    p = sub.add_parser("gdc", help="Build a manifest from the GDC files API.")

    facets = p.add_argument_group("guided filters")
    facets.add_argument("--project", help="Project id, e.g. TCGA-BRCA (comma-separated for several).")
    facets.add_argument("--primary-site", dest="primary_site", help="e.g. Breast, Lung, Brain.")
    facets.add_argument("--disease-type", dest="disease_type")
    facets.add_argument("--data-category", dest="data_category")
    facets.add_argument("--data-type", dest="data_type")
    facets.add_argument("--experimental-strategy", dest="experimental_strategy")
    facets.add_argument("--workflow-type", dest="workflow_type", help="Analysis workflow, e.g. 'STAR - Counts'.")
    facets.add_argument("--platform", dest="platform")
    facets.add_argument("--data-format", dest="data_format")
    facets.add_argument("--access", help="open or controlled.")
    facets.add_argument("--sample-type", dest="sample_type")

    cohort = p.add_argument_group("cohort lists (match an uploaded set of ids)")
    cohort.add_argument("--file-id-list", dest="file_id_list",
                        help="Path to a file of GDC file ids (one per line) to match.")
    cohort.add_argument("--case-list", dest="case_list",
                        help="Path to a file of case submitter ids/barcodes (one per line).")
    cohort.add_argument("--sample-list", dest="sample_list",
                        help="Path to a file of sample submitter ids/barcodes (one per line).")

    adv = p.add_argument_group("advanced filters")
    adv.add_argument("--extra-filter", dest="extra_filters", action="append", default=[],
                     metavar="field=F;op=in;values=a,b", help="Custom facet (repeatable).")
    adv.add_argument("--raw-filters", dest="raw_filters", help="Path to a raw GDC filters JSON file.")

    q = p.add_argument_group("query")
    q.add_argument("--max-files", type=int, help="Cap the number of files in the manifest.")
    q.add_argument("--count-only", action="store_true", help="Preview match counts; do not build.")

    enr = p.add_argument_group("enrichment (optional)")
    enr.add_argument("--cbioportal-study", dest="cbioportal_study",
                     help="One study id, or several comma-separated to merge "
                          "(e.g. brca_tcga_pan_can_atlas_2018,brca_tcga for PAM50 + ER/PR/HER2).")
    enr.add_argument("--cbioportal-attrs", dest="cbioportal_attrs", help="Comma list of attribute ids, or 'all'.")
    enr.add_argument("--cbioportal-base", dest="cbioportal_base", default=cbioportal.DEFAULT_BASE)
    enr.add_argument("--cbioportal-list-attrs", action="store_true",
                     help="Write the study's clinical attributes to the report and exit.")
    enr.add_argument("--annotation-tsv", dest="annotation_tsv")
    enr.add_argument("--annotation-key-col", dest="annotation_key_col", default="sample")

    j = p.add_argument_group("join")
    j.add_argument("--join-level", dest="join_level", choices=("patient", "sample", "full"), default="sample")
    j.add_argument("--no-trim-vial", dest="trim_vial", action="store_false", default=True,
                   help="Do not trim the vial letter (01A) when normalizing sample barcodes.")

    out = p.add_argument_group("outputs")
    out.add_argument("--manifest-out", default="gdc_manifest.txt")
    out.add_argument("--metadata-out", default="metadata.tsv")
    out.add_argument("--report-out", default="report.tsv")
    p.add_argument("--verbose", action="store_true")
    return parser


def _provenance(filters: dict) -> dict:
    """Build the run's provenance record (source, endpoint, query, when, version)."""
    import datetime

    return {
        "source": "gdc",
        "endpoint": gdc.FILES_ENDPOINT,
        "tool_version": version_string(),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "query_filters": json.dumps(filters, sort_keys=True, separators=(",", ":")),
    }


def _read_id_list(path: str | None) -> list[str]:
    """Read a cohort id file into a list (one id per line; blanks/#comments skipped)."""
    if not path:
        return []
    with open(path) as fh:
        return [
            line.strip()
            for line in fh
            if line.strip() and not line.lstrip().startswith("#")
        ]


def _run_gdc(args: argparse.Namespace) -> int:
    session = build_session()

    # Normalise and sanity-check the cBioPortal study id(s) early, before the
    # (expensive) GDC query, so a bad id fails fast with a clear message.
    # One or more comma-separated ids are allowed (they get merged).
    if args.cbioportal_study:
        studies = enrich.split_studies(args.cbioportal_study)
        bad = [s for s in studies if any(c.isspace() for c in s)]
        if bad:
            raise InputError(
                f"cBioPortal study id(s) must be bare ids like 'brca_tcga' "
                f"(comma-separate several), not {bad!r}. No flag names or spaces inside an id."
            )
        args.cbioportal_study = ",".join(studies)

    # Discovery helper: list cBioPortal attributes and stop.
    if args.cbioportal_list_attrs:
        if not args.cbioportal_study:
            raise InputError("--cbioportal-list-attrs requires --cbioportal-study.")
        rows = []
        for study in enrich.split_studies(args.cbioportal_study):
            for a in cbioportal.list_attributes(session, study, base=args.cbioportal_base):
                rows.append(("cbioportal_attribute", a.get("clinicalAttributeId", ""),
                             f"{study}: {a.get('displayName', '')}"))
        io.write_manifest(args.manifest_out, [])
        io.write_metadata(args.metadata_out, [], [])
        io.write_report(args.report_out, extra=rows)
        log.info("Wrote %d cBioPortal attribute(s) to the report.", len(rows))
        return 0

    raw = None
    if args.raw_filters:
        with open(args.raw_filters) as fh:
            raw = json.load(fh)
    filters = build_filters(
        project=args.project,
        primary_site=args.primary_site,
        disease_type=args.disease_type,
        data_category=args.data_category,
        data_type=args.data_type,
        experimental_strategy=args.experimental_strategy,
        workflow_type=args.workflow_type,
        platform=args.platform,
        data_format=args.data_format,
        access=args.access,
        sample_type=args.sample_type,
        file_id_list=_read_id_list(args.file_id_list),
        case_list=_read_id_list(args.case_list),
        sample_list=_read_id_list(args.sample_list),
        extra_filters=args.extra_filters,
        raw_filters=raw,
    )
    prov = _provenance(filters)

    if args.count_only:
        total = gdc.count(session, filters)
        facet_counts = gdc.facets(session, filters, PREVIEW_FACETS)
        io.write_manifest(args.manifest_out, [])
        io.write_metadata(args.metadata_out, [], [])
        io.write_report(args.report_out, database_total=total, facets=facet_counts, provenance=prov)
        log.info("Preview: %d file(s) match the filters.", total)
        return 0

    total_matching = gdc.count(session, filters)
    file_rows = gdc.query_files(session, filters, max_files=args.max_files, total=total_matching)
    # Drop rows without a file id: the GaCDI GDC importer skips empty-id manifest
    # rows, so excluding them keeps the manifest and metadata table aligned.
    dropped = [r for r in file_rows if not r.file_id]
    if dropped:
        log.warning("Dropped %d file(s) with no file id.", len(dropped))
    file_rows = [r for r in file_rows if r.file_id]
    # Deterministic order so the manifest is reproducible across runs (workflows).
    file_rows.sort(key=lambda r: r.file_id)

    # No files matched: write empty, self-explanatory outputs and skip the
    # (now pointless) annotation fetch/join.
    if not file_rows:
        io.write_manifest(args.manifest_out, [])
        io.write_metadata(args.metadata_out, [], [])
        io.write_report(
            args.report_out,
            database_total=total_matching,
            provenance=prov,
            extra=[(
                "note",
                "no_files_matched",
                "No files matched your filters. Check that the filters are compatible — "
                "e.g. Data format must match the Data type (Slide Image files are SVS, not TSV). "
                "Try 'Preview counts only' while adjusting filters.",
            )],
        )
        log.warning("No files matched the filters; wrote empty manifest and a note.")
        return 0

    annotations, ann_cols = enrich.collect(
        session,
        cbioportal_study=args.cbioportal_study,
        cbioportal_attrs=args.cbioportal_attrs,
        cbioportal_base=args.cbioportal_base,
        annotation_tsv=args.annotation_tsv,
        annotation_key_col=args.annotation_key_col,
    )
    merged, report = join(
        file_rows,
        annotations,
        level=args.join_level,
        trim_vial=args.trim_vial,
        annotation_columns=ann_cols,
    )
    io.write_manifest(args.manifest_out, file_rows)
    io.write_metadata(args.metadata_out, merged, ann_cols)
    io.write_report(
        args.report_out,
        database_total=total_matching,
        merged_rows=merged,
        report=report,
        enrichment_columns=ann_cols,
        provenance=prov,
    )
    log.info(
        "Built manifest with %d file(s); %d matched to annotation, %d unmatched.",
        report.total_files,
        report.matched_files,
        len(report.unmatched_files),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # Emit the running version to the job log so it is visible in Galaxy's job info.
    log.info("gacdi-manifest %s", version_string())
    try:
        if args.database == "gdc":
            return _run_gdc(args)
        raise InputError(f"Unknown database '{args.database}'.")
    except ManifestError as exc:
        log.error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
