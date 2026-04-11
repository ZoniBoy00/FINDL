from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, DOUBLE_EDGE
import time
from findl.config import APP_VERSION

console = Console()

class UI:
    @staticmethod
    def banner():
        banner_text = Text()
        banner_text.append(" ███████╗██╗███╗   ██╗██████╗ ██╗     \n", style="bold cyan")
        banner_text.append(" ██╔════╝██║████╗  ██║██╔══██╗██║     \n", style="bold cyan")
        banner_text.append(" █████╗  ██║██╔██╗ ██║██║  ██║██║     \n", style="bold white")
        banner_text.append(" ██╔══╝  ██║██║╚██╗██║██║  ██║██║     \n", style="bold white")
        banner_text.append(" ██║     ██║██║ ╚████║██████╔╝███████╗\n", style="bold blue")
        banner_text.append(" ╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝", style="bold blue")

        panel = Panel(
            Text.assemble(banner_text, "\n\n", (f" Unified Video Downloader v{APP_VERSION} ", "bold italic white on blue")),
            border_style="blue",
            box=DOUBLE_EDGE,
            padding=(1, 2)
        )
        console.print(panel)

    @staticmethod
    def print_step(title, status="running"):
        icons = {"running": "🌎", "success": "✅", "error": "❌", "info": "ℹ️"}
        icon = icons.get(status, "●")
        console.print(f"\n[bold]{icon} {title}[/bold]")

    @staticmethod
    def playback_table(info):
        table = Table(show_header=True, header_style="bold magenta", box=ROUNDED, expand=True)
        table.add_column("Property", style="dim", width=15)
        table.add_column("Value", style="bold cyan")
        
        table.add_row("Manifest", (info.get("manifest_url", "N/A")[:80] + "...") if info.get("manifest_url") else "N/A")
        table.add_row("License", info.get("license_url", "N/A"))
        
        pssh = info.get("pssh") or "Pending..."
        pssh_style = "green" if info.get("pssh") else "yellow"
        table.add_row("PSSH", Text(pssh[:50] + "...", style=pssh_style))
        
        table.add_row("Subtitles", f"[bold white]{len(info.get('subtitles', []))}[/bold white] found")
        
        console.print(Panel(table, title="[bold cyan]Extraction Result[/bold cyan]", border_style="cyan"))

    @staticmethod
    def key_panel(keys):
        if not keys:
            console.print(Panel("[bold red]No decryption keys found![/bold red]", border_style="red"))
            return

        key_text = Text()
        for i, key in enumerate(keys):
            key_text.append(f"  🔑 Key {i+1}: ", style="bold white")
            key_text.append(f"{key}\n", style="bold green")
            
        console.print(Panel(key_text, title=f"[bold green]Decryption Keys ({len(keys)})[/bold green]", border_style="green", box=ROUNDED))

    @staticmethod
    def download_session(title, output, keys, subs):
        grid = Table.grid(expand=True)
        grid.add_column(style="bold blue", width=15)
        grid.add_column(style="white")
        
        grid.add_row("Title:", title)
        grid.add_row("Output:", output)
        grid.add_row("Keys:", f"{len(keys)} loaded")
        grid.add_row("Subtitles:", f"{len(subs)} found")
        
        console.print(Panel(grid, title="[bold yellow]Download Task[/bold yellow]", border_style="yellow", padding=(1, 2)))

    @staticmethod
    def success_panel(title, output, duration):
        summary = Table.grid(expand=True)
        summary.add_column(style="dim", width=15)
        summary.add_column()
        
        summary.add_row("File:", f"[bold cyan]{title}.mkv[/bold cyan]")
        summary.add_row("Location:", output)
        summary.add_row("Time:", f"{duration:.1f}s")
        summary.add_row("Status:", "[bold green]Completed Successfully[/bold green]")
        
        console.print(Panel(summary, title="[bold green]Success[/bold green]", border_style="green", padding=(1, 2), box=DOUBLE_EDGE))

    @staticmethod
    def error(msg):
        console.print(f"\n[bold red]Error:[/bold red] {msg}")

    @staticmethod
    def status(msg):
        return console.status(f"[bold cyan]{msg}")
