"""kitapai komut satırı arayüzü.

    kitapai doctor                    ortam denetimi
    kitapai data download             Open Library dump'larını indir
    kitapai data build --dumps DIR    katalogu kur
    kitapai dataset build             eğitim verisini üret
    kitapai index build               gömme indeksini kur
    kitapai train                     QLoRA ince ayarı
    kitapai eval                      modeli ölç
    kitapai serve                     API'yi başlat
    kitapai ask "karanlık distopya"   terminalden tek seferlik öneri
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, paths
from .config import get_settings
from .logging import setup

app = typer.Typer(
    name="kitapai", no_args_is_help=True, add_completion=False,
    help="Open Library kataloğuna dayalı Türkçe kitap öneri sistemi",
)
data_app = typer.Typer(no_args_is_help=True, help="Dump indirme ve katalog kurulumu")
dataset_app = typer.Typer(no_args_is_help=True, help="Eğitim verisi üretimi")
index_app = typer.Typer(no_args_is_help=True, help="Gömme indeksi")
export_app = typer.Typer(no_args_is_help=True, help="Model dışa aktarma")
app.add_typer(data_app, name="data")
app.add_typer(dataset_app, name="dataset")
app.add_typer(index_app, name="index")
app.add_typer(export_app, name="export")

console = Console()


def _human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


# ── doctor ─────────────────────────────────────────────────────────────────


@app.command()
def doctor() -> None:
    """Ortamı denetler: disk, GPU, katalog, indeks, adaptör, bağımlılıklar."""
    setup()
    settings = get_settings()
    table = Table(title="kitapai ortam denetimi", show_lines=False)
    table.add_column("Bileşen", style="bold")
    table.add_column("Durum")
    table.add_column("Ayrıntı", overflow="fold")

    def row(name: str, ok: bool | None, detail: str) -> None:
        mark = {True: "[green]tamam[/]", False: "[red]eksik[/]", None: "[yellow]uyarı[/]"}[ok]
        table.add_row(name, mark, detail)

    # Disk
    usage = shutil.disk_usage(paths.project_root())
    free_gb = usage.free / 2**30
    disk_state = True if free_gb > 60 else (None if free_gb > 25 else False)
    row("disk", disk_state,
        f"{_human(usage.free)} boş — tam dump için ~60 GiB, "
        f"sadece katalog için ~25 GiB önerilir")

    # GPU
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 2**30
            row("gpu", True, f"{name} · {vram:.1f} GiB VRAM")
        else:
            row("gpu", None,
                "CUDA yok — eğitim yapılamaz, servis `stub`/`openai` motoruyla çalışır")
    except ImportError:
        row("gpu", None, "torch kurulu değil (veri hattı ve servis için gerekmez)")

    # Katalog
    catalog = settings.catalog_file
    if catalog.exists():
        import duckdb

        try:
            con = duckdb.connect(str(catalog), read_only=True)
            count = con.execute("SELECT count(*) FROM books").fetchone()[0]
            meta = con.execute(
                "SELECT value FROM catalog_meta WHERE key='build'"
            ).fetchone()
            con.close()
            dump_date = json.loads(meta[0]).get("dump_date") if meta else None
            row("katalog", count > 0,
                f"{count:,} kitap · {_human(catalog.stat().st_size)} · dump {dump_date or '?'}")
        except Exception as exc:
            row("katalog", False, f"okunamadı: {exc}")
    else:
        row("katalog", False, f"{catalog} yok — `kitapai data build` çalıştırın")

    # Gömme indeksi
    meta_file = settings.vectors_dir / "meta.json"
    if meta_file.exists():
        info = json.loads(meta_file.read_text(encoding="utf-8"))
        row("gömme indeksi", True,
            f"{info.get('count', 0):,} vektör × {info.get('dim', '?')} · {info.get('model')}")
    else:
        row("gömme indeksi", None, f"{settings.vectors_dir} yok — yalnız BM25 kullanılır")

    # Adaptörler (iki aşamalı boru hattı: SEÇ + YAZ)
    from .prompting import PROMPT_VERSION

    for name, adapter in (("seçici adaptör", settings.select_adapter_dir),
                          ("yazıcı adaptör", settings.write_adapter_dir)):
        meta_path = adapter / "kitapai_meta.json"
        if meta_path.exists():
            info = json.loads(meta_path.read_text(encoding="utf-8"))
            same = info.get("prompt_version") == PROMPT_VERSION
            row(name, same or None,
                f"{info.get('base_model')} · istem sürümü {info.get('prompt_version')}"
                + ("" if same else f" ≠ kod sürümü {PROMPT_VERSION} (yeniden eğitim gerekir)"))
        elif adapter.exists():
            row(name, None, f"{adapter} var ama künye yok")
        else:
            row(name, None, f"{adapter} yok — `kitapai train -c configs/train-"
                            f"{'select' if 'seçici' in name else 'write'}.yaml`")

    # Eğitim verisi
    ds = paths.data_dir() / "dataset" / "train.jsonl"
    row("eğitim verisi", ds.exists(),
        f"{_human(ds.stat().st_size)}" if ds.exists() else "yok — `kitapai dataset build`")

    # Bağımlılıklar
    for module, label, needed_for in (
        ("duckdb", "duckdb", "veri hattı"),
        ("sentence_transformers", "sentence-transformers", "gömme araması"),
        ("unsloth", "unsloth", "eğitim"),
        ("transformers", "transformers", "yerel model"),
    ):
        try:
            __import__(module)
            row(label, True, needed_for)
        except ImportError:
            row(label, None, f"kurulu değil — {needed_for} için gerekli")

    console.print(table)


# ── data ───────────────────────────────────────────────────────────────────


@data_app.command("download")
def data_download(
    dest: Path = typer.Option(None, "--dir", help="hedef dizin (varsayılan: data/dumps)"),
    only: str = typer.Option(
        "", "--only", help="virgülle: works,editions,authors,ratings,reading-log"
    ),
) -> None:
    """Open Library dump dosyalarını indirir (kesintiden sonra devam eder)."""
    setup()
    from rich.progress import BarColumn, Progress, TextColumn, TransferSpeedColumn

    from .data.download import download_all

    target = dest or paths.dumps_dir()
    target.mkdir(parents=True, exist_ok=True)
    kinds = [k.strip() for k in only.split(",") if k.strip()] or None

    with Progress(TextColumn("{task.description}"), BarColumn(),
                  TextColumn("{task.percentage:>3.0f}%"), TransferSpeedColumn(),
                  console=console) as progress:
        tasks: dict[str, int] = {}

        def on_progress(kind: str, done: int, total: int | None) -> None:
            if kind not in tasks:
                tasks[kind] = progress.add_task(kind, total=total)
            progress.update(tasks[kind], completed=done, total=total)

        results = download_all(target, kinds=kinds, progress=on_progress)

    for r in results:
        state = "atlandı" if r.skipped else ("devam" if r.resumed else "indirildi")
        console.print(f"  {r.kind:12} {state:9} {_human(r.bytes_total)}  {r.path.name}")


@data_app.command("build")
def data_build(
    dumps: Path = typer.Option(None, "--dumps", help="dump dizini"),
    remote: bool = typer.Option(False, "--remote", help="hepsini diske indirmeden akıt"),
    allow_remote: bool = typer.Option(
        False, "--allow-remote",
        help="yerelde olmayan dump'ları diske indirmeden akıt (karma mod)",
    ),
    out: Path = typer.Option(None, "--out", help="katalog dosyası"),
    limit_works: int = typer.Option(None, "--limit", help="geliştirme için eser sınırı"),
    memory: str = typer.Option("3GB", "--memory", help="DuckDB bellek sınırı"),
    threads: int = typer.Option(4, "--threads"),
    temp_dir: Path = typer.Option(None, "--temp-dir", help="taşma dizini (büyük disk önerilir)"),
    keep_stages: bool = typer.Option(False, "--keep-stages", help="ara tabloları sakla"),
    resume: bool = typer.Option(
        False, "--resume", help="yarım kalmış katalogu kaldığı yerden sürdür"),
    stop_after: str = typer.Option(
        "", "--stop-after",
        help="bu aşamadan sonra dur (authors|works|prelim|editions|candidates|books)"),
    no_editions: bool = typer.Option(
        False, "--no-editions",
        help="baskı dump'ını atla (sayfa/ISBN/dil/Türkçe başlık boş kalır)"),
) -> None:
    """Dump'lardan sorgulanabilir katalogu kurar."""
    setup()
    from .data import sources
    from .data.catalog import BuildOptions, build_catalog

    settings = get_settings()
    target = out or settings.catalog_file
    dumps_dir = dumps or paths.dumps_dir()
    if remote:
        src = sources.from_remote()
    elif allow_remote:
        src = sources.mixed(dumps_dir)
    else:
        # `--resume` ile tamamlanmış aşamaların dump'ı artık gerekmiyor
        # (örn. `prelim` çıkarıldıktan sonra 3.8 GB'lık works dosyası silinebilir).
        missing: tuple[str, ...] = ()
        if resume:
            missing = ("works", "editions", "authors", "ratings", "reading-log")
        elif no_editions:
            missing = ("editions",)
        src = sources.from_directory(dumps_dir, allow_missing=missing)

    options = BuildOptions(
        limit_works=limit_works, memory_limit=memory, threads=threads,
        temp_dir=str(temp_dir) if temp_dir else None, preserve_stages=keep_stages,
        resume=resume, skip_editions=no_editions,
        stop_after=stop_after or None,
    )
    report = build_catalog(src, target, options)
    console.print_json(json.dumps(report.as_dict(), ensure_ascii=False))


@data_app.command("stats")
def data_stats(top: int = typer.Option(10, "--top")) -> None:
    """Katalog özeti: kitap sayısı, tür dağılımı, kapsama oranları."""
    setup()
    import duckdb

    settings = get_settings()
    con = duckdb.connect(str(settings.catalog_file), read_only=True)
    total = con.execute("SELECT count(*) FROM books").fetchone()[0]
    console.print(f"[bold]{total:,}[/] kitap · {settings.catalog_file}")

    coverage = con.execute("""
        SELECT
          round(100.0 * count(*) FILTER (WHERE cover_id IS NOT NULL) / count(*), 1) AS kapak,
          round(100.0 * count(*) FILTER (WHERE description IS NOT NULL) / count(*), 1) AS aciklama,
          round(100.0 * count(*) FILTER (WHERE len(genres) > 0) / count(*), 1) AS tur,
          round(100.0 * count(*) FILTER (WHERE rating_count > 0) / count(*), 1) AS puan,
          round(100.0 * count(*) FILTER (
            WHERE list_contains(languages, 'tur')) / count(*), 1) AS turkce
        FROM books
    """).fetchone()
    table = Table(title="kapsama (%)")
    for name in ("kapak", "açıklama", "tür etiketi", "puan", "Türkçe baskı"):
        table.add_column(name)
    table.add_row(*[str(v) for v in coverage])
    console.print(table)

    genre_table = Table(title=f"en yaygın {top} tür")
    genre_table.add_column("tür")
    genre_table.add_column("kitap", justify="right")
    # `unnest` GROUP BY ile aynı SELECT'te kullanılamaz; önce açıp sonra sayıyoruz.
    for slug, count in con.execute(f"""
        SELECT g, count(*) AS n
        FROM (SELECT unnest(genres) AS g FROM books)
        GROUP BY g ORDER BY n DESC LIMIT {top}
    """).fetchall():
        genre_table.add_row(slug, f"{count:,}")
    console.print(genre_table)
    con.close()


# ── dataset ────────────────────────────────────────────────────────────────


@dataset_app.command("build")
def dataset_build(
    samples: int = typer.Option(20000, "--samples", "-n"),
    out: Path = typer.Option(None, "--out"),
    pool: int = typer.Option(120000, "--pool", help="bellekteki çalışma havuzu"),
    seed: int = typer.Option(20260918, "--seed"),
    candidates: int = typer.Option(14, "--candidates", help="istemdeki aday sayısı"),
) -> None:
    """Katalogdan sentetik eğitim verisi üretir."""
    setup()
    from .dataset.build import DatasetOptions, build_dataset

    settings = get_settings()
    target = out or (paths.data_dir() / "dataset")
    stats = build_dataset(
        settings.catalog_file, target,
        DatasetOptions(samples=samples, pool_size=pool, seed=seed, candidates=candidates),
    )
    console.print_json(json.dumps(stats.as_dict(), ensure_ascii=False))


@dataset_app.command("relabel")
def dataset_relabel(
    src: Path = typer.Option(None, "--src", help="girdi (varsayılan select_train.jsonl)"),
    out: Path = typer.Option(None, "--out", help="çıktı (varsayılan select_train_judged.jsonl)"),
    n: int = typer.Option(6000, "--n", help="işlenecek ilk n örnek"),
    cache: Path = typer.Option(None, "--cache", help="not önbelleği JSONL"),
    workers: int = typer.Option(16, "--workers"),
    model: str = typer.Option(None, "--model"),
) -> None:
    """Seçim etiketlerini Gemini hakem notlarıyla yeniden yazar (0 notlu kitap seçilmez)."""
    setup()
    from .dataset.distill import DEFAULT_MODEL, GeminiClient
    from .evaluation import judge as J

    base = paths.data_dir() / "dataset"
    src = src or base / "select_train.jsonl"
    out = out or base / (src.stem + "_judged.jsonl")
    cache = cache or Path("runs") / f"judge-ratings-{src.stem}.jsonl"
    client = GeminiClient(model=model or DEFAULT_MODEL)
    ratings = J.judge_samples(client, src, cache, samples=n, workers=workers)
    rows = J._load_rows(src, n)
    relabeled, stats = J.relabel_rows(rows, ratings)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in relabeled) + "\n",
                   encoding="utf-8")
    console.print(f"[green]yazıldı:[/] {out}  {stats}")
    console.print(f"[dim]hakem kullanımı: {client.usage}[/]")


@dataset_app.command("distill")
def dataset_distill(
    n: int = typer.Option(50, "--n", "-n", help="kaç örnek (pilot için 50)"),
    start: int = typer.Option(0, "--start", help="kaynak dosyada başlangıç indeksi"),
    source: Path = typer.Option(None, "--source", help="şablonlu train.jsonl"),
    out: Path = typer.Option(
        None, "--out", help="çıktı (varsayılan: data/dataset/distilled.jsonl)"),
    model: str = typer.Option("gemini-3.8-flash", "--model"),
    project: str = typer.Option("flint-client", "--project"),
    auth: str = typer.Option("key", "--auth", help="key (GCLOUD_API_KEY) | adc"),
    workers: int = typer.Option(6, "--workers"),
) -> None:
    """Şablon gerekçeleri bir LLM'e (Vertex AI Gemini) yeniden yazdırır. Devam edilebilir.

    Seçim ve güven puanı kural tabanlı kalır; yalnızca `why`/`hooks` metni değişir.
    Gerçek token kullanımı sonda raporlanır — maliyet varsayımla değil bununla hesaplanır.
    """
    setup()
    from .dataset.distill import DistillError, GeminiClient, distill_file

    src = source or (paths.data_dir() / "dataset" / "train.jsonl")
    dst = out or (paths.data_dir() / "dataset" / "distilled.jsonl")
    try:
        client = GeminiClient(project=project, model=model, auth=auth)
    except DistillError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    report = distill_file(client, src, dst, limit=n, start=start, workers=workers)
    console.print_json(json.dumps(report.__dict__, ensure_ascii=False, default=str))


@dataset_app.command("stages")
def dataset_stages(
    directory: Path = typer.Option(None, "--dir", help="veri dizini (varsayılan data/dataset)"),
) -> None:
    """train/valid/distilled dosyalarından SEÇ ve YAZ görev dosyalarını türetir."""
    setup()
    from .dataset.stages import build_stages

    counts = build_stages(directory or (paths.data_dir() / "dataset"))
    for name, n in counts.items():
        console.print(f"  {name:14} {n:>7,}")


@dataset_app.command("preview")
def dataset_preview(
    n: int = typer.Option(3, "--n"),
    path: Path = typer.Option(None, "--path"),
) -> None:
    """Üretilen örnekleri okunur biçimde gösterir."""
    setup()
    target = path or (paths.data_dir() / "dataset" / "train.jsonl")
    with target.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            row = json.loads(line)
            console.rule(f"örnek {i + 1} · {row['meta']['style']}")
            console.print(row["messages"][1]["content"])
            console.print("[bold green]HEDEF[/]")
            console.print_json(row["messages"][2]["content"])


# ── index ──────────────────────────────────────────────────────────────────


@index_app.command("build")
def index_build(
    limit: int = typer.Option(300000, "--limit", help="en bilinen N kitap gömülür"),
    batch: int = typer.Option(64, "--batch"),
    model: str = typer.Option(None, "--model"),
) -> None:
    """Anlamsal arama için gömme indeksini kurar."""
    setup()
    import duckdb

    from .retrieval.dense import DenseIndex
    from .retrieval.hybrid import Retriever

    settings = get_settings()
    con = duckdb.connect(str(settings.catalog_file), read_only=True)
    cols = Retriever.SELECT
    rows = con.execute(
        f"SELECT {cols} FROM books ORDER BY popularity DESC LIMIT {limit}"
    ).fetchall()
    names = [c.strip() for c in cols.split(",")]
    records = [dict(zip(names, r, strict=True)) for r in rows]
    con.close()

    DenseIndex.build(
        records, settings.vectors_dir,
        model_name=model or settings.embedding_model, batch_size=batch,
    )


# ── eğitim / değerlendirme ─────────────────────────────────────────────────


@app.command()
def train(
    config: Path = typer.Option(None, "--config", "-c", help="YAML yapılandırma"),
    resume: bool = typer.Option(False, "--resume"),
    max_steps: int = typer.Option(
        0, "--max-steps",
        help="duman testi: yalnızca bu kadar adım eğit (örn. 20) — bellek ve hızı görmek için"),
) -> None:
    """QLoRA ince ayarı."""
    setup()
    from .train.config import TrainConfig
    from .train.train import train as run_train

    cfg = TrainConfig.load(config)
    console.print(f"[bold]eğitim başlıyor[/] — {cfg.base_model}, {cfg.epochs} tur")
    meta = run_train(cfg, resume=resume, max_steps=max_steps or None)
    console.print_json(json.dumps(meta, ensure_ascii=False))


@export_app.command("merge")
def export_merge(
    out: Path = typer.Option(None, "--out"),
    base: str = typer.Option(None, "--base"),
) -> None:
    """LoRA adaptörünü taban modele işler."""
    setup()
    from .train.export import merge

    settings = get_settings()
    merge(settings.adapter_dir, base or settings.base_model,
          out or (paths.models_dir() / "kitapai-merged"))


@export_app.command("gguf")
def export_gguf(
    merged: Path = typer.Option(None, "--merged"),
    out: Path = typer.Option(None, "--out"),
    quant: str = typer.Option("q4_k_m", "--quant"),
) -> None:
    """Birleştirilmiş modeli GGUF'a çevirir (llama.cpp için)."""
    setup()
    from .train.export import to_gguf

    src = merged or (paths.models_dir() / "kitapai-merged")
    to_gguf(src, out or (paths.models_dir() / f"kitapai-{quant}.gguf"), quantization=quant)


@app.command("eval")
def eval_command(
    mode: str = typer.Option("select", "--mode", help="select | write | legacy (eski v1-v3)"),
    samples: int = typer.Option(100, "--samples", "-n"),
    path: Path = typer.Option(None, "--path", help="doğrulama JSONL (varsayılan moda göre)"),
    out: Path = typer.Option(None, "--out", help="sonucu JSON olarak yaz"),
    record: Path = typer.Option(None, "--record", help="örnek başına seçimleri JSONL'e yaz"),
    batch: int = typer.Option(8, "--batch", help="toplu üretim boyutu"),
) -> None:
    """Doğrulama kümesinde modeli ölçer."""
    setup()
    from .evaluation.run import MODES, evaluate
    from .serve.engine import create_engine

    if mode not in MODES:
        raise typer.BadParameter(f"mod şunlardan biri olmalı: {', '.join(MODES)}")
    settings = get_settings()
    defaults = {"select": "select_valid.jsonl", "write": "write_valid.jsonl",
                "legacy": "valid.jsonl"}
    target = path or (paths.data_dir() / "dataset" / defaults[mode])
    engine = create_engine(settings, legacy=(mode == "legacy"))
    result = evaluate(engine, target, samples=samples, mode=mode,
                      batch_size=batch, record_path=record)

    table = Table(title=f"değerlendirme · {mode} · {engine.name} · {engine.model_id}")
    table.add_column("ölçüt")
    table.add_column("değer", justify="right")
    for key, value in result.as_dict().items():
        if key != "failures":
            table.add_row(key, f"{value}")
    console.print(table)
    for f in result.failures[:10]:
        console.print(f"  · [yellow]{f}[/]")
    if out:
        out.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")


@app.command("judge-write")
def judge_write_command(
    records: list[str] = typer.Argument(
        None, help="etiket=kayıt.jsonl (eval --mode write --record çıktısı)"),
    samples: int = typer.Option(100, "--samples", "-n"),
    path: Path = typer.Option(None, "--path", help="varsayılan write_valid.jsonl"),
    cache: Path = typer.Option(Path("runs/judge-write.jsonl"), "--cache"),
    workers: int = typer.Option(8, "--workers"),
    model: str = typer.Option(None, "--model"),
) -> None:
    """Gemini ile yazılan gerekçelerin kitap bilgisiyle desteklenip desteklenmediğini notlar."""
    setup()
    from .dataset.distill import DEFAULT_MODEL, GeminiClient
    from .evaluation import judge as J

    target = path or (paths.data_dir() / "dataset" / "write_valid.jsonl")
    client = GeminiClient(model=model or DEFAULT_MODEL)
    sources = [("referans(damıtma)", J.reference_writing_records(target, samples))]
    for spec in records or []:
        label, _, file = spec.partition("=")
        if not file:
            raise typer.BadParameter(f"'etiket=dosya' biçiminde olmalı: {spec}")
        sources.append((label, J.load_records(Path(file))))
    table = Table(title=f"yazıcı hakemi · {client.model}")
    cols = ["label", "n", "items", "grounded", "fabricated", "useful"]
    for c in cols:
        table.add_column(c, justify="left" if c == "label" else "right")
    for label, recs in sources:
        rated = J.judge_writing(client, target, recs[:samples], cache, workers=workers)
        d = J.score_writing(label, rated).as_dict()
        table.add_row(*[str(d[c]) for c in cols])
    console.print(table)
    console.print("[dim]grounded/useful: 0-2 · fabricated: dayanak=0 alan gerekçe oranı[/]")


@app.command("judge")
def judge_command(
    records: list[str] = typer.Argument(
        None, help="etiket=kayıt.jsonl (eval --record çıktısı); birden çok model verilebilir"),
    samples: int = typer.Option(100, "--samples", "-n"),
    path: Path = typer.Option(None, "--path", help="aday kümesi (varsayılan select_valid.jsonl)"),
    cache: Path = typer.Option(Path("runs/judge-ratings.jsonl"), "--cache"),
    workers: int = typer.Option(8, "--workers"),
    model: str = typer.Option(None, "--model"),
    out: Path = typer.Option(None, "--out", help="sonucu JSON olarak yaz"),
) -> None:
    """Gemini'yi hakem olarak kullanıp modellerin seçimlerini notlar (0-2)."""
    setup()
    from .dataset.distill import DEFAULT_MODEL, GeminiClient
    from .evaluation import judge as J

    target = path or (paths.data_dir() / "dataset" / "select_valid.jsonl")
    client = GeminiClient(model=model or DEFAULT_MODEL)
    ratings = J.judge_samples(client, target, cache, samples=samples, workers=workers)
    limits = J.limits_for(target, samples)
    loaded: list[tuple[str, list[dict]]] = []
    for spec in records or []:
        label, _, file = spec.partition("=")
        if not file:
            raise typer.BadParameter(f"'etiket=dosya' biçiminde olmalı: {spec}")
        loaded.append((label, J.load_records(Path(file))))
    # Farklı örnek sayılarıyla ölçülmüş modeller adil kıyaslansın: ortak kümeye indir.
    common = set(ratings)
    for _, recs in loaded:
        common &= {r["i"] for r in recs}
    pick = lambda recs: [r for r in recs if r["i"] in common]  # noqa: E731
    scores = [J.score_records("referans", pick(J.reference_records(target, samples)),
                              ratings, limits)]
    scores += [J.score_records(label, pick(recs), ratings, limits) for label, recs in loaded]

    table = Table(title=f"hakem · {client.model} · {len(ratings)} örnek")
    cols = ["label", "n", "mean_grade", "good_rate", "bad_rate", "no_pick", "normalized"]
    for c in cols:
        table.add_column(c, justify="left" if c == "label" else "right")
    for sc in scores:
        d = sc.as_dict()
        table.add_row(*[str(d[c]) for c in cols])
    base = scores[0].as_dict()
    table.caption = f"rastgele={base['random_grade']} · ideal={base['ideal_grade']} (0-2)"
    console.print(table)
    console.print(f"[dim]hakem kullanımı: {client.usage}[/]")
    if out:
        out.write_text(json.dumps([s.as_dict() for s in scores], ensure_ascii=False, indent=2),
                       encoding="utf-8")


# ── servis ─────────────────────────────────────────────────────────────────


@app.command()
def serve(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """API sunucusunu başlatır."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "kitapai.serve.app:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def ask(
    query: str = typer.Argument(..., help="serbest metin istek"),
    limit: int = typer.Option(3, "--limit", "-n"),
    genres: str = typer.Option("", "--genres", help="virgülle tür slug'ları"),
    moods: str = typer.Option("", "--moods"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Sunucu başlatmadan terminalden tek seferlik öneri alır."""
    setup()
    import asyncio

    import duckdb

    from .retrieval.dense import DenseIndex
    from .retrieval.hybrid import Retriever
    from .schemas import RecommendRequest
    from .serve.engine import create_engine
    from .serve.pipeline import RecommendPipeline

    settings = get_settings()
    con = duckdb.connect(str(settings.catalog_file), read_only=True)
    retriever = Retriever(con, DenseIndex.load(settings.vectors_dir))
    pipeline = RecommendPipeline(retriever, create_engine(settings), settings)

    request = RecommendRequest(
        query=query, limit=limit,
        genres=[g.strip() for g in genres.split(",") if g.strip()],
        moods=[m.strip() for m in moods.split(",") if m.strip()],
    )
    result = asyncio.run(pipeline.recommend(request))
    con.close()

    if json_out:
        console.print_json(result.response.model_dump_json())
        return

    for rec in result.response.recommendations:
        book = rec.book
        console.rule(f"{rec.rank}. {book.title}")
        meta = " · ".join(filter(None, [
            ", ".join(book.authors), str(book.first_published or ""),
            f"{book.pages} sayfa" if book.pages else "",
            f"puan {book.rating.average:.1f}" if book.rating else "",
        ]))
        console.print(f"[dim]{meta}[/]")
        console.print(rec.why)
        if rec.hooks:
            console.print(f"[cyan]{' · '.join(rec.hooks)}[/]")
        if rec.content_notes:
            console.print(f"[yellow]uyarı: {', '.join(rec.content_notes)}[/]")
        console.print(f"[dim]{book.openlibrary_url}[/]")
    for f in result.response.followups:
        console.print(f"\n[italic]{f}[/]")


@app.command()
def version() -> None:
    """Sürüm bilgisi."""
    from .prompting import PROMPT_VERSION

    console.print(f"kitapai {__version__} · istem sürümü {PROMPT_VERSION}")


if __name__ == "__main__":
    app()
