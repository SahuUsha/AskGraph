import os
import base64
import glob
import threading

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend BEFORE importing pyplot
import matplotlib.pyplot as plt
import seaborn as sns

# pyplot keeps global figure state, so two threadpool workers running generated
# scripts at once can steal each other's figures. Every exec of a generated
# script is serialised behind this.
# ponytail: one process-wide lock; move plotting to a subprocess pool if chart
# throughput ever matters more than isolation.
_PLOT_LOCK = threading.Lock()

# Names the generated script is allowed to touch. Anything absent is a
# NameError inside the exec, which the retry loop reports as a normal viz
# failure. Chosen by what matplotlib/pandas snippets actually use.
# Design rules shared by the first-pass and repair prompts. Kept in one place
# so a fix attempt can't quietly drop the styling the first pass was told to use.
CHART_DESIGN_RULES = """        CHART DESIGN RULES:
        - Pick the form from the data, not habit:
            time/date on one axis      -> line chart (sorted by date)
            ranking across categories  -> horizontal barh, sorted longest-first
            one numeric distribution   -> histogram
            two numerics               -> scatter
            part-to-whole, <=5 slices  -> pie/donut; MORE than 5 -> bar instead
        - Never plot a raw row dump. If the data is granular, aggregate first.
        - Cap categorical axes at the top 12 by value; group the remainder into
          a single 'Other' bar rather than rendering an unreadable axis.
        - Sort bars by value (descending), never alphabetically by accident.
        - Titles: a short sentence stating the takeaway ("Revenue peaked in Q3"),
          not a restatement of the column names.
        - Axis labels: Title Case from the column name, underscores replaced by
          spaces, with units where known. Never leave a raw column name like
          `sum_amt_usd` on display.
        - Format tick numbers for humans: thousands separators, and K/M/B
          suffixes above 10,000. Never leave scientific notation (1e6) on an axis.
        - Rotate x tick labels 30-45 degrees with ha='right' only when they
          overlap; keep them horizontal when they fit.
        - Annotate bar values directly on the bars when there are <= 12 bars.
        - Use figsize=(10, 6), dpi=110, sns.set_style('whitegrid'), and a single
          coherent palette. Drop the top and right spines.
        - Always call plt.tight_layout() before saving.
        - Handle nulls explicitly: drop or label them, never let them render as
          a blank category."""

_ALLOWED_BUILTINS = {
    'abs', 'all', 'any', 'bool', 'dict', 'divmod', 'enumerate', 'filter',
    'float', 'format', 'frozenset', 'getattr', 'hasattr', 'int', 'isinstance',
    'issubclass', 'iter', 'len', 'list', 'map', 'max', 'min', 'next', 'print',
    'range', 'repr', 'reversed', 'round', 'set', 'setattr', 'slice', 'sorted',
    'str', 'sum', 'tuple', 'type', 'zip',
    'True', 'False', 'None',
    'ValueError', 'TypeError', 'KeyError', 'IndexError', 'Exception',
    'AttributeError', 'ZeroDivisionError', 'RuntimeError', 'StopIteration',
}


class VizService:
    @staticmethod
    def _log_failed_viz_script(
        script: str,
        error: Exception | str,
        query: str,
        attempt: int,
        columns: list[str] | None = None,
    ) -> None:
        print(f"\n--- Failed viz script (attempt {attempt}) ---")
        print(f"query: {query}")
        print(f"columns: {columns or []}")
        print(f"error: {error}")
        print("script:")
        print(script if script else "# (empty script)")
        print("--- end failed viz script ---\n")

    @staticmethod
    def _prepare_viz_script(script: str) -> str:
        """Drop import lines — they hit the sandbox __import__ guard and fail."""
        lines = []
        for line in (script or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    @staticmethod
    def _exec_globals(df: pd.DataFrame, temp_dir: str) -> dict:
        g = VizService.safe_exec_globals()
        g["df"] = df.copy()
        g["output_dir"] = temp_dir
        g["chart_path"] = os.path.join(temp_dir, "chart.png")
        return g

    @staticmethod
    def _fallback_chart(df: pd.DataFrame, temp_dir: str, query: str) -> None:
        """Deterministic bar chart when model-written scripts fail."""
        plt.close("all")
        sns.set_style("whitegrid")
        fig, ax = plt.subplots(figsize=(10, 6))
        cols = list(df.columns)
        if len(cols) < 2:
            raise ValueError("Need at least two columns for a fallback chart.")

        label_col, value_col = cols[0], cols[1]
        plot_df = df.head(12).copy()
        labels = plot_df[label_col].astype(str)
        values = pd.to_numeric(plot_df[value_col], errors="coerce").fillna(0)
        order = values.sort_values(ascending=True).index
        ax.barh(labels.loc[order], values.loc[order])
        ax.set_xlabel(str(value_col).replace("_", " ").title())
        ax.set_ylabel(str(label_col).replace("_", " ").title())
        title = (query or "Chart").split(".")[0][:80]
        ax.set_title(title)
        sns.despine(top=True, right=True)
        plt.tight_layout()
        plt.savefig(os.path.join(temp_dir, "chart.png"), dpi=110, bbox_inches="tight")
        plt.close(fig)

    @staticmethod
    def safe_exec_globals():
        """Globals for exec() of model-written plotting code.

        Python injects the real builtins into any globals dict that lacks a
        '__builtins__' key, so omitting it left __import__ reachable and made
        this endpoint remote code execution. Pin a safelist instead.
        """
        import builtins

        safe_builtins = {
            name: getattr(builtins, name)
            for name in _ALLOWED_BUILTINS
            if hasattr(builtins, name)
        }

        def forbidden_op(*args, **kwargs):
            raise ValueError("EXEC SECURITY: This operation is forbidden.")

        # No __import__, open, eval, exec, compile, globals, vars, or input.
        for blocked in ('__import__', 'open', 'eval', 'exec', 'compile',
                        'input', 'exit', 'quit', 'globals', 'vars', 'breakpoint'):
            safe_builtins[blocked] = forbidden_op

        return {
            '__builtins__': safe_builtins,
            'pd': pd,
            'plt': plt,
            'sns': sns,
            'exit': forbidden_op,
            'quit': forbidden_op,
            'print': print,
        }

    @staticmethod
    def generate_visualizations(df: pd.DataFrame, query: str, ai_service, temp_dir: str,
                                single_chart: bool = False) -> list:
        csv_path = os.path.join(temp_dir, "data.csv")
        df.to_csv(csv_path, index=False)

        # Provide sample rows so AI can see actual data formats
        sample_rows = df.head(3).to_string(index=False)
        dtypes_info = df.dtypes.to_string()

        # Dashboard tiles show one chart each, so asking for several and
        # discarding all but the first just burns tokens and plot time.
        count_rule = (
            "- Produce EXACTLY ONE chart. Save exactly one .png file."
            if single_chart else
            "- Use plt.figure() for each chart."
        )

        viz_prompt = f"""
        You are a data visualization engineer. Write a Python script that turns
        the data below into a chart a business reader can read in 3 seconds.

        Context (what the reader asked): {query}
        Input CSV: '{csv_path}'  ({len(df)} rows)
        Columns: {df.columns.tolist()}
        Data Types:
        {dtypes_info}
        Sample Data (first 3 rows):
        {sample_rows}

        Output: save with plt.savefig(chart_path, dpi=110, bbox_inches='tight').

{CHART_DESIGN_RULES}

        TECHNICAL RULES (violating these breaks the run):
        {count_rule}
        - The script runs in a restricted sandbox. Only `pd`, `plt`, `sns`, `df`,
          `output_dir`, and `chart_path` are available and ALREADY set up. Do NOT
          write any import statement — imports fail with EXEC SECURITY.
        - `df` already holds the query result. Do NOT call pd.read_csv() or open().
        - Save the chart to `chart_path` via plt.savefig(chart_path, ...).
        - NO plt.show(). NO exit(). NO quit(). NO open(). NO eval/exec/globals().
        - Do NOT use infer_datetime_format parameter in pd.to_datetime().
        - For date parsing, use pd.to_datetime(col, format='mixed') or pd.to_datetime(col, format='ISO8601'). NEVER guess a manual format string.
        - When using seaborn plots with a 'palette', you MUST also assign the 'hue' parameter (e.g. `hue=x` or `hue=y`) and set `legend=False` to avoid FutureWarnings.
        - Return ONLY executable Python code. No markdown fences or explanation.
        - Wrap optional refinements in try/except so a cosmetic failure never
          loses the chart.
        """
        py_script = VizService._prepare_viz_script(
            ai_service.gemini_call(viz_prompt, "Generate Viz Code")
        )

        max_retries = 2
        attempts = 0
        graphs = []

        while attempts <= max_retries:
            try:
                with _PLOT_LOCK:
                    plt.close('all')
                    exec_globals = VizService._exec_globals(df, temp_dir)
                    exec(py_script, exec_globals)
                    for img in sorted(glob.glob(os.path.join(temp_dir, "*.png"))):
                        with open(img, "rb") as f:
                            graphs.append(base64.b64encode(f.read()).decode('utf-8'))
                    plt.close('all')
                break  # Success — exit the retry loop
            except Exception as e:
                plt.close('all')
                attempts += 1
                VizService._log_failed_viz_script(
                    script=py_script,
                    error=e,
                    query=query,
                    attempt=attempts,
                    columns=df.columns.tolist(),
                )
                if attempts <= max_retries:
                    print(f"🔄 Viz error on attempt {attempts}: {e}. Retrying with corrected script...")
                    # Clean up any partial/broken PNGs from the failed attempt
                    for stale_img in glob.glob(os.path.join(temp_dir, "*.png")):
                        try:
                            os.remove(stale_img)
                        except OSError:
                            pass
                    fix_prompt = f"""
                    The following Python visualization script failed with an error.
                    Fix the cause of the error and return ONLY the corrected
                    Python code. No markdown. Keep the chart design intact —
                    fix the fault, do not fall back to a bare default plot.

                    Original Script:
                    {py_script}

                    Error:
                    {e}

{CHART_DESIGN_RULES}

                    TECHNICAL RULES:
                    {count_rule}
                    - Only `pd`, `plt`, `sns`, `df`, `output_dir`, and `chart_path`
                      are available and ALREADY set up. Do NOT write imports.
                    - Use the preloaded `df`. Do NOT call pd.read_csv() or open().
                    - Save with plt.savefig(chart_path, dpi=110, bbox_inches='tight').
                    - NO plt.show(). NO exit(). NO quit(). NO open(). NO eval/exec/globals().
                    - Do NOT use infer_datetime_format parameter in pd.to_datetime().
                    - For date parsing, use pd.to_datetime(col, format='mixed') or pd.to_datetime(col, format='ISO8601'). NEVER guess a manual format string.
                    - When using seaborn plots with a 'palette', you MUST also assign the 'hue' parameter (e.g. `hue=x` or `hue=y`) and set `legend=False` to avoid FutureWarnings.
                    - Return ONLY executable Python code. No markdown fences or explanation.
                    - Columns: {df.columns.tolist()}. Sample data:
                    {sample_rows}
                    """
                    py_script = VizService._prepare_viz_script(
                        ai_service.gemini_call(fix_prompt, "Fix Viz Code")
                    )
                    if not py_script:
                        print("❌ AI failed to generate corrected viz script.")
                        VizService._log_failed_viz_script(
                            script="",
                            error="AI returned empty corrected script",
                            query=query,
                            attempt=attempts,
                            columns=df.columns.tolist(),
                        )
                        break
                else:
                    print(f"❌ Viz generation failed after {max_retries + 1} attempts: {e}")
                    try:
                        with _PLOT_LOCK:
                            plt.close('all')
                            VizService._fallback_chart(df, temp_dir, query)
                            print("📊 Used fallback chart after viz script failures.")
                            for img in sorted(glob.glob(os.path.join(temp_dir, "*.png"))):
                                with open(img, "rb") as f:
                                    graphs.append(base64.b64encode(f.read()).decode('utf-8'))
                            plt.close('all')
                    except Exception as fallback_err:
                        print(f"❌ Fallback chart also failed: {fallback_err}")

        return graphs
