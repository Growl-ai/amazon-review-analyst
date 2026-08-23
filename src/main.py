# main.py
from typing import Any
import argparse
from graph import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asin", required=False, default="")
    parser.add_argument("--csv", required=False, default="/Users/lyinlu/CBEcommerce/agents/data/pet_sling_reviews.csv")
    parser.add_argument("--product-title", required=False, default="")
    parser.add_argument("--max-reviews", type=int, default=50)
    parser.add_argument("--cache-base-dir", required=False, default="")
    parser.add_argument("--tagging-mode", required=False, default="sequential")
    args = parser.parse_args()

    asin = (args.asin or "").strip()
    csv_path = (args.csv or "").strip()
    if not asin and not csv_path:
        raise SystemExit("必须指定 --asin 或 --csv")
    if not asin and csv_path:
        asin = "CSV_INPUT"

    inputs = {"asin": asin, "max_reviews": args.max_reviews}
    if csv_path:
        inputs["input_csv"] = csv_path
    if args.product_title:
        inputs["product_title"] = args.product_title
    if args.cache_base_dir:
        inputs["cache_base_dir"] = args.cache_base_dir
    if args.tagging_mode:
        import os as _os

        _os.environ["TAGGING_MODE"] = args.tagging_mode

    final_state = dict[str, Any](inputs)
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"--- 完成节点: {key} ---")
            if isinstance(value, dict):
                final_state.update(value)

    print("\n\n✅ 最终报告生成完毕！\n")
    print(final_state.get("final_report") or "")
    export_paths = final_state.get("export_paths") or {}
    if export_paths:
        print("\n\n📄 导出文件：")
        for k, v in export_paths.items():
            print(f"- {k}: {v}")
