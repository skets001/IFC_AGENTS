"""CLI entry point for IFC Intelligence Agent.

Usage:
    ifc-agent check model.ifc                    # Run all checks
    ifc-agent check model.ifc --check spatial     # Run specific check
    ifc-agent check model.ifc --format html       # Output format
    ifc-agent serve                               # Start MCP server
    ifc-agent anonymise model.ifc output.ifc      # Strip PII
    ifc-agent info model.ifc                      # Model summary
"""

import sys
import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="ifc-agent")
def main():
    """IFC Intelligence Agent — check, enrich, and validate IFC models."""
    pass

@main.group()
def bep():
    """BIM Execution Plan (BEP) Rule Engine."""
    pass

@bep.command("parse")
@click.argument("document_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output Rules YAML path.")
def bep_parse(document_path, output):
    """Parse a BEP PDF/DOCX and generate a YAML rule pack."""
    from ifc_agent.bep_parser.ingest import extract_text
    from ifc_agent.bep_parser.extractor import extract_rules_to_yaml
    
    console.print(f"\n📄 [bold]Ingesting Document:[/bold] {document_path}")
    text = extract_text(document_path)
    console.print(f"   Extracted {len(text)} characters of context. Sending to LLM...")
    
    if not output:
        output = Path(document_path).with_suffix(".yaml")
        
    try:
        extract_rules_to_yaml(text, output_yaml_path=output)
        console.print(f"✅ [bold green]Success![/bold green] YAML rules extracted to: {output}\n")
    except Exception as e:
        console.print(f"❌ [bold red]Extraction Failed:[/bold red] {e}\n")

@bep.command("compile")
@click.argument("yaml_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output IDS XML file.")
def bep_compile(yaml_path, output):
    """Compile a YAML rule pack into an IDS XML validation file."""
    from ifc_agent.bep_parser.compiler import compile_yaml_to_ids
    
    console.print(f"\n⚙️  [bold]Compiling YAML:[/bold] {yaml_path}")
    if not output:
        output = Path(yaml_path).with_suffix(".ids")
        
    try:
        spec = compile_yaml_to_ids(yaml_path, output_ids_path=output)
        console.print(f"✅ [bold green]Compiled {len(spec.specifications)} specifications![/bold green] Saved to: {output}\n")
    except Exception as e:
        console.print(f"❌ [bold red]Compilation Failed:[/bold red] {e}\n")

@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output path for classified model.")
def classify(file_path, output):
    """Automatically resolve IfcBuildingElementProxy elements using LLM."""
    from ifc_agent.classification.proxy_extractor import extract_proxies
    from ifc_agent.classification.bsdd_resolver import infer_class
    from ifc_agent.classification.mutator import classify_and_mutate
    import ifcopenshell
    
    console.print(f"\n🔍 [bold]Scanning for Proxies in:[/bold] {file_path}")
    model = ifcopenshell.open(file_path)
    proxies = extract_proxies(model)
    
    if not proxies:
        console.print("✅ [bold green]No IfcBuildingElementProxy elements found![/bold green] Model is clean.\n")
        return
        
    console.print(f"⚠️  Found {len(proxies)} Unclassified Proxy Elements. Initiating AI Engine...")
    
    predictions = {}
    for i, proxy in enumerate(proxies):
        console.print(f"   [{i+1}/{len(proxies)}] Inferring type for: '{proxy.get('name', 'Unnamed')}' ({proxy['global_id']})")
        predicted_class = infer_class(proxy)
        console.print(f"      ↳ AI Prediction: [bold cyan]{predicted_class}[/bold cyan]")
        predictions[proxy['global_id']] = predicted_class
        
    console.print("\n⚙️  [bold]Restructuring IFC Schema...[/bold]")
    res = classify_and_mutate(file_path, predictions, output_path=output)
    
    console.print(f"✅ [bold green]Success![/bold green] Mutated {res['mutated_count']} elements.")
    console.print(f"💾 Saved resolved model to: {res['output_path']}\n")


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output path for enriched model.")
def enrich(file_path, output):
    """Deterministically populate missing COBie properties using AI inference."""
    from ifc_agent.enrichment.harvester import harvest_metadata
    from ifc_agent.enrichment.ai_mapper import extract_cobie_parameters
    from ifc_agent.enrichment.injector import evaluate_and_inject
    import ifcopenshell
    
    console.print(f"\n🔍 [bold]Scanning for eligible objects in:[/bold] {file_path}")
    model = ifcopenshell.open(file_path)
    metadata = harvest_metadata(model)
    
    if not metadata:
        console.print("✅ [bold green]No incomplete elements requiring enrichment were found.[/bold green]\n")
        return
        
    console.print(f"⚠️  Found {len(metadata)} elements missing standard Manufacturer/Model fields.")
    
    injection_map = {}
    for i, meta in enumerate(metadata):
        console.print(f"   [{i+1}/{len(metadata)}] AI analyzing context for '{meta.get('name', 'Unnamed')}' ({meta['ifc_class']})")
        extracted = extract_cobie_parameters(meta)
        
        valid_props = {k: v for k, v in extracted.items() if v is not None}
        if valid_props:
            console.print(f"      ↳ Deduced: {valid_props}")
            injection_map[meta['global_id']] = valid_props
        else:
            console.print("      ↳ [dim]No strict parameters deduced.[/dim]")
            
    console.print("\n⚙️  [bold]Injecting standard COBie Psets...[/bold]")
    res = evaluate_and_inject(file_path, injection_map, output_path=output)
    
    console.print(f"✅ [bold green]Success![/bold green] Pushed {res['properties_added']} properties across {res['elements_mutated']} elements.")
    console.print(f"💾 Saved enriched model to: {res['output_path']}\n")


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option(
    "--check", "-c",
    multiple=True,
    help="Specific check(s) to run. Options: schema, ids, spatial, guid, proxy, type",
)
@click.option(
    "--format", "-f", "output_format",
    type=click.Choice(["console", "json", "html"]),
    default="console",
    help="Output format.",
)
@click.option("--ids", "ids_path", type=click.Path(), help="Path to IDS XML file.")
@click.option("--output", "-o", type=click.Path(), help="Output directory for reports.")
def check(file_path, check, output_format, ids_path, output):
    """Run baseline checks on an IFC file."""
    from ifc_agent.checker.runner import run_all
    from ifc_agent.checker import report as report_module

    console.print(f"\n🏗️  [bold]Checking:[/bold] {Path(file_path).name}\n")

    checks = list(check) if check else None
    report = run_all(
        file_path,
        checks=checks,
        ids_path=ids_path,
        output_dir=output,
    )

    if output_format == "json":
        json_str = report_module.to_json(report)
        if output:
            out_path = Path(output) / f"{Path(file_path).stem}_report.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json_str, encoding="utf-8")
            console.print(f"📄 JSON report: {out_path}")
        else:
            click.echo(json_str)

    elif output_format == "html":
        out_dir = Path(output) if output else Path(file_path).parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{Path(file_path).stem}_report.html"
        report_module.to_html(report, html_path)
        console.print(f"📄 HTML report: [link={html_path}]{html_path}[/link]")

    else:
        # Console output with Rich
        _print_console_report(report)

    # Always show summary
    console.print(f"\n{report.telegram_summary}\n")


def _print_console_report(report):
    """Pretty-print the checker report to console using Rich."""
    # Overall status
    if report.overall_passed:
        console.print(Panel(
            f"[bold green]✅ ALL CHECKS PASSED[/bold green]\n"
            f"{report.checks_passed}/{report.checks_run} checks · "
            f"{report.total_issues} issues · {report.duration_seconds}s",
            box=box.ROUNDED,
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[bold red]❌ ISSUES FOUND[/bold red]\n"
            f"{report.checks_passed}/{report.checks_run} passed · "
            f"{report.checks_failed} failed · "
            f"{report.total_issues} issues · {report.duration_seconds}s",
            box=box.ROUNDED,
            border_style="red",
        ))

    # Results table
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    table.add_column("Check", style="bold", width=10)
    table.add_column("Status", width=8)
    table.add_column("Summary", min_width=40)

    for check_name, result in report.results.items():
        r = result.to_dict()
        status = "[green]✓ PASS[/green]" if r["passed"] else "[red]✗ FAIL[/red]"
        table.add_row(check_name.upper(), status, r["summary"])

    console.print(table)

    # Detail sections for failures
    for check_name, result in report.results.items():
        r = result.to_dict()
        if r["passed"]:
            continue

        issues = []
        if check_name == "spatial":
            issues = r.get("orphans", [])[:10]
        elif check_name == "guid":
            issues = r.get("duplicates", [])[:10]
        elif check_name == "proxy":
            issues = r.get("groups", [])[:10]
        elif check_name == "type":
            issues = r.get("untyped_elements", [])[:10]

        if issues:
            detail_table = Table(
                title=f"\n{check_name.upper()} Details",
                box=box.MINIMAL,
                show_header=True,
            )
            if check_name == "proxy":
                detail_table.add_column("Pattern")
                detail_table.add_column("Count")
                for item in issues:
                    detail_table.add_row(item["pattern"], str(item["count"]))
            else:
                detail_table.add_column("GlobalId", style="dim")
                detail_table.add_column("Name")
                detail_table.add_column("Class")
                for item in issues:
                    detail_table.add_row(
                        item.get("global_id", item.get("guid", "—")),
                        item.get("name", "—"),
                        item.get("ifc_class", "—"),
                    )
            console.print(detail_table)


@main.command()
@click.option("--host", default="127.0.0.1", help="Server host.")
@click.option("--port", "-p", default=8000, help="Server port.")
def serve(host, port):
    """Start the IFC MCP server."""
    console.print(f"\n🚀 Starting IFC MCP Server on [bold]{host}:{port}[/bold]\n")
    console.print("Tools available:")
    console.print("  [cyan]Query:[/cyan]    load_model, get_entities, get_entity_properties, get_entities_in_spatial")
    console.print("  [cyan]Checker:[/cyan]  run_baseline_check, get_proxies, get_orphan_elements")
    console.print("  [cyan]Privacy:[/cyan]  get_safe_metadata")
    console.print(f"\n  Endpoint: [link=http://{host}:{port}/mcp]http://{host}:{port}/mcp[/link]\n")

    from ifc_agent.mcp_server.server import start_server
    start_server(host=host, port=port)


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
def anonymise(file_path, output_path):
    """Strip personal/sensitive fields from an IFC file."""
    import ifcopenshell
    from ifc_agent.anonymiser.strip import strip_personal_fields

    console.print(f"\n🔒 Anonymising: {Path(file_path).name}")

    model = ifcopenshell.open(str(file_path))
    result = strip_personal_fields(model, output_path)

    console.print(f"   Entities processed: {result.entities_processed}")
    console.print(f"   Fields stripped:    {result.fields_stripped}")
    console.print(f"   Output: {output_path}\n")

    if result.errors:
        for err in result.errors:
            console.print(f"   [yellow]⚠ {err}[/yellow]")


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
def info(file_path):
    """Show summary information about an IFC file."""
    import ifcopenshell

    console.print(f"\n📋 [bold]IFC File Info:[/bold] {Path(file_path).name}\n")

    model = ifcopenshell.open(str(file_path))

    # Basic info
    console.print(f"  Schema:   {model.schema}")
    console.print(f"  Entities: {len(list(model))}")

    # Project
    projects = model.by_type("IfcProject")
    if projects:
        console.print(f"  Project:  {projects[0].Name or 'unnamed'}")

    # Site
    sites = model.by_type("IfcSite")
    if sites:
        console.print(f"  Site:     {sites[0].Name or 'unnamed'}")

    # Building
    buildings = model.by_type("IfcBuilding")
    if buildings:
        console.print(f"  Building: {buildings[0].Name or 'unnamed'}")

    # Key counts
    console.print("\n  [bold]Element counts:[/bold]")
    for type_name in [
        "IfcWall", "IfcDoor", "IfcWindow", "IfcSlab", "IfcColumn",
        "IfcBeam", "IfcSpace", "IfcStairFlight", "IfcRoof",
        "IfcBuildingElementProxy", "IfcFurnishingElement",
        "IfcFlowTerminal", "IfcUnitaryEquipment",
    ]:
        count = len(model.by_type(type_name))
        if count > 0:
            style = "[yellow]" if type_name == "IfcBuildingElementProxy" else ""
            end_style = "[/yellow]" if style else ""
            console.print(f"    {style}{type_name}: {count}{end_style}")

    console.print()


@main.command("__main__")
@click.pass_context
def run_main(ctx):
    """Entry point for python -m ifc_agent."""
    ctx.invoke(main)


# Allow running as module
if __name__ == "__main__":
    main()
