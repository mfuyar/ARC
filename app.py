#!/usr/bin/env python3
"""Flask web app for HOA/ARC PDF review."""

import argparse
import os
import tempfile
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from pdf_review_helper import compare_pdf_files

app = Flask(__name__)  # pylint: disable=invalid-name
app.secret_key = os.environ.get("SECRET_KEY") or "change-me-in-production"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB


def _is_pdf(file_storage) -> bool:
    header = file_storage.read(4)
    file_storage.seek(0)
    return header == b"%PDF"


@app.route("/")
def index():
    return render_template("index.html")


PARK_AVENUE_GUIDELINE = Path(__file__).parent / "guidelines" / "park_avenue.pdf"
PARK_AVENUE_GUIDELINE_TXT = Path(__file__).parent / "guidelines" / "park_avenue.txt"


@app.route("/review", methods=["POST"])
def review():
    is_park_avenue = request.form.get("is_park_avenue") == "true"
    application_file = request.files.get("application_pdf")

    if not application_file or not application_file.filename:
        flash("Please upload the ARC application PDF.")
        return redirect(url_for("index"))

    if not _is_pdf(application_file):
        flash("The ARC application file does not appear to be a valid PDF.")
        return redirect(url_for("index"))

    # Resolve guideline source
    if is_park_avenue:
        if PARK_AVENUE_GUIDELINE_TXT.exists():
            guideline_path = str(PARK_AVENUE_GUIDELINE)  # helper checks .txt alongside .pdf
        elif PARK_AVENUE_GUIDELINE.exists():
            guideline_path = str(PARK_AVENUE_GUIDELINE)
        else:
            flash(
                "The Park Avenue HOA guideline is not set up on this server yet. "
                "Please contact the administrator or upload your own guideline PDF."
            )
            return redirect(url_for("index"))
        owns_guideline_temp = False
    else:
        guideline_file = request.files.get("guideline_pdf")
        if not guideline_file or not guideline_file.filename:
            flash("Please upload the HOA guideline PDF.")
            return redirect(url_for("index"))
        if not _is_pdf(guideline_file):
            flash("The HOA guideline file does not appear to be a valid PDF.")
            return redirect(url_for("index"))
        guideline_fd, guideline_path = tempfile.mkstemp(suffix=".pdf")
        os.close(guideline_fd)
        guideline_file.save(guideline_path)
        owns_guideline_temp = True

    application_fd, application_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.close(application_fd)
        application_file.save(application_path)
        result = compare_pdf_files(
            Path(guideline_path),
            Path(application_path),
            is_park_avenue=is_park_avenue,
        )
        if result.get("error"):
            flash(result["error"])
            return redirect(url_for("index"))
    except ValueError as exc:
        flash(f"Could not read PDF: {exc}")
        return redirect(url_for("index"))
    except Exception as exc:
        flash(f"Error: {exc}")
        return redirect(url_for("index"))
    finally:
        try:
            os.unlink(application_path)
        except OSError:
            pass
        if owns_guideline_temp:
            try:
                os.unlink(guideline_path)
            except OSError:
                pass

    return render_template("result.html", review=result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HOA/ARC review web app.")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0", port=args.port)
