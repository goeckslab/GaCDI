"""CLI: ``gacdi-manifest <database> [...]`` — build manifests + enriched metadata.

Source-specific work lives in each :class:`~gacdi_manifest.importer.BuildImporter`
(see ``sources/``); this module owns the shared runner: preview/count, the
annotation join, the post-query metadata filter, and writing the three outputs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from gacdi_core.errors import InputError as ContractInputError

from . import cbioportal, enrich, io, postfilter, selection, version_string
from .errors import InputError, ManifestError
from .importer import BuildImporter
from .join import join
from .net import build_session
from .registry import REGISTRY, get_importer, get_source

log = logging.getLogger("gacdi_manifest")


def _add_common_arguments(p: argparse.ArgumentParser) -> None:
    """Flags shared by every source (post-query filtering, enrichment, outputs)."""
    adv = p.add_argument_group("post-query filter")
    adv.add_argument("--metadata-filter", dest="metadata_filters", action="append", default=[],
                     metavar="column=C;op=present;values=a,b",
                     help="Post-query filter on a generated metadata column; trims the final "
                          "manifest/metadata to matching samples (repeatable). "
                          "Ops: present, blank, in, exclude, contains.")

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
    out.add_argument(
        "--selection-manifest-out",
        help="Canonical retrieval-asset TSV (default: selection_manifest.tsv beside --manifest-out).",
    )
    out.add_argument(
        "--selection-metadata-out",
        help="Canonical association metadata TSV (default: selection_metadata.tsv beside --manifest-out).",
    )
    out.add_argument(
        "--selection-provenance-out",
        help="Canonical provenance JSON (default: selection_provenance.json beside --manifest-out).",
    )
    p.add_argument("--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gacdi-manifest", description="GaCDI manifest builder.")
    parser.add_argument("--version", action="version", version=f"gacdi-manifest {version_string()}")
    sub = parser.add_subparsers(dest="database", required=True, metavar="DATABASE")

    # Subparsers are built by iterating the registry: each source adds its own
    # query flags, then the shared flags are appended. A source import failure is
    # recorded on that subparser so the other commands remain usable and choosing
    # the unavailable source produces a clean error. Deliberately keep
    # add_arguments() outside the exception handler: parser-definition bugs must
    # fail loudly instead of silently producing an incomplete command surface.
    for name in sorted(REGISTRY):
        spec = REGISTRY[name]
        p = sub.add_parser(name, help=spec.help)
        try:
            source = get_source(name)
        except Exception as exc:  # noqa: BLE001 - isolate an unavailable source module
            p.set_defaults(
                _source_load_error=f"{type(exc).__name__}: {exc}"
            )
        else:
            source.add_arguments(p)
        _add_common_arguments(p)
    return parser


def _write_manifest(importer: BuildImporter, path: str, file_rows: list) -> None:
    """Write the manifest in the importer's dialect: strict GDC, or §4.1 for new sources."""
    if importer.manifest_dialect == "source":
        io.write_source_manifest(path, importer.to_manifest_rows(file_rows))
    else:
        io.write_manifest(path, file_rows)


def _resolve_selection_paths(args: argparse.Namespace) -> None:
    defaults = selection.default_output_paths(args.manifest_out)
    for attribute, default in zip(
        ("selection_manifest_out", "selection_metadata_out", "selection_provenance_out"),
        defaults,
    ):
        if not getattr(args, attribute):
            setattr(args, attribute, default)


def _write_selection_outputs(
    importer: BuildImporter,
    args: argparse.Namespace,
    *,
    file_rows: list,
    merged_rows: list[dict],
    query,
    provenance: dict | None,
    mode: str,
    source_matches: int | None,
    warnings: list[str] | None = None,
    extra_counts: dict | None = None,
) -> None:
    try:
        selection.write_selection_bundle(
            importer=importer,
            file_rows=file_rows,
            merged_rows=merged_rows,
            manifest_path=args.selection_manifest_out,
            metadata_path=args.selection_metadata_out,
            provenance_path=args.selection_provenance_out,
            query=query,
            source_provenance=provenance,
            annotation_requested=bool(args.cbioportal_study or args.annotation_tsv),
            mode=mode,
            source_matches=source_matches,
            warnings=warnings,
            extra_counts=extra_counts,
        )
    except ContractInputError as exc:
        # Keep one stable selector error hierarchy/exit code even though canonical
        # validation is shared with the downloader package.
        raise InputError(f"Canonical selection output failed validation: {exc}") from exc


def _run(importer: BuildImporter, args: argparse.Namespace) -> int:
    session = build_session()
    _resolve_selection_paths(args)

    # Normalise and sanity-check the cBioPortal study id(s) early, before the
    # (expensive) source query, so a bad id fails fast with a clear message.
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
        _write_manifest(importer, args.manifest_out, [])
        io.write_metadata(args.metadata_out, [], [])
        io.write_report(args.report_out, extra=rows)
        _write_selection_outputs(
            importer,
            args,
            file_rows=[],
            merged_rows=[],
            query={
                "operation": "cbioportal_list_attributes",
                "studies": enrich.split_studies(args.cbioportal_study),
            },
            provenance={
                "endpoint": args.cbioportal_base,
            },
            mode="preview",
            source_matches=0,
            warnings=["Attribute-list mode does not enumerate retrieval assets."],
            extra_counts={"cbioportal_attributes": len(rows)},
        )
        log.info("Wrote %d cBioPortal attribute(s) to the report.", len(rows))
        return 0

    query = importer.build_query(args)
    prov = importer.provenance(query)

    if args.count_only:
        total = importer.count(session, query)
        facet_counts = importer.facets(session, query)
        _write_manifest(importer, args.manifest_out, [])
        io.write_metadata(args.metadata_out, [], [])
        io.write_report(args.report_out, database_total=total, facets=facet_counts, provenance=prov)
        _write_selection_outputs(
            importer,
            args,
            file_rows=[],
            merged_rows=[],
            query=query,
            provenance=prov,
            mode="preview",
            source_matches=total,
        )
        log.info("Preview: %d file(s) match the filters.", total)
        return 0

    total_matching = importer.count(session, query)
    file_rows = importer.fetch(session, query, max_files=args.max_files, total=total_matching)
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
        _write_manifest(importer, args.manifest_out, [])
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
        empty_warnings = ["No retrieval assets matched the source query."]
        if dropped:
            empty_warnings.append(f"Dropped {len(dropped)} source row(s) without an asset identifier.")
        _write_selection_outputs(
            importer,
            args,
            file_rows=[],
            merged_rows=[],
            query=query,
            provenance=prov,
            mode="build",
            source_matches=total_matching,
            warnings=empty_warnings,
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
        source=importer.name,
    )

    # Best-effort harmonization: let the source map its native passthrough columns
    # into the harmonized metadata core (GDC is a no-op — its join already fills it).
    for row in merged:
        for col, val in importer.harmonize(row).items():
            if val and not row.get(col):
                row[col] = val

    # Second-layer (post-query) filtering on the generated metadata columns.
    # Trims the final outputs to the samples the user cares about; a file stays in
    # the manifest as long as at least one of its (file x sample) rows survives.
    post_notes: list[tuple[str, str, str]] = []
    if args.metadata_filters:
        before = len(merged)
        merged = postfilter.apply_metadata_filters(
            merged, args.metadata_filters, columns=io.metadata_columns(ann_cols, merged)
        )
        kept_ids = {r.get("file_id") for r in merged}
        file_rows = [r for r in file_rows if r.file_id in kept_ids]
        # Keep the QC report consistent with the trimmed rows.
        file_counts = Counter(r.get("file_id") for r in merged)
        report.total_files = len(file_counts)
        report.matched_files = sum(1 for r in merged if r.get("matched") == "yes")
        report.unmatched_files = [r["file_id"] for r in merged if r.get("matched") == "no"]
        report.multi_sample_files = sum(1 for n in file_counts.values() if n > 1)
        for spec in args.metadata_filters:
            post_notes.append(("metadata_filter", "applied", spec))
        post_notes.append(("metadata_filter", "rows_kept", f"{len(merged)} of {before}"))
        post_notes.append(("metadata_filter", "files_kept", str(len(file_counts))))
        log.info("Metadata filter kept %d of %d row(s) across %d file(s).",
                 len(merged), before, len(file_counts))

    _write_manifest(importer, args.manifest_out, file_rows)
    io.write_metadata(args.metadata_out, merged, ann_cols)
    io.write_report(
        args.report_out,
        database_total=total_matching,
        merged_rows=merged,
        report=report,
        enrichment_columns=ann_cols,
        provenance=prov,
        extra=post_notes or None,
    )
    selection_warnings = []
    if dropped:
        selection_warnings.append(
            f"Dropped {len(dropped)} source row(s) without an asset identifier."
        )
    if args.metadata_filters and not file_rows:
        selection_warnings.append("Post-query metadata filters removed every retrieval asset.")
    _write_selection_outputs(
        importer,
        args,
        file_rows=file_rows,
        merged_rows=merged,
        query=query,
        provenance=prov,
        mode="build",
        source_matches=total_matching,
        warnings=selection_warnings,
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
        source_load_error = getattr(args, "_source_load_error", "")
        if source_load_error:
            raise InputError(
                f"Manifest source '{args.database}' is unavailable: {source_load_error}"
            )
        importer = get_importer(args.database)
        return _run(importer, args)
    except ManifestError as exc:
        log.error("%s", exc)
        return exc.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
