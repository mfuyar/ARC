#!/usr/bin/env python3
"""Flask web app for HOA/ARC PDF review."""

import argparse
import logging
import os
import tempfile
from pathlib import Path

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, url_for

logging.basicConfig(level=logging.INFO)

import io
import json

from pdf_generator import generate_arc_application
from pdf_review_helper import compare_pdf_files, extract_project_types, get_application_guidance

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


@app.route("/sitemap.xml")
def sitemap():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url>"
        "<loc>https://ezarc-friendly-review.lovable.app/</loc>"
        "<changefreq>monthly</changefreq>"
        "<priority>1.0</priority>"
        "</url>"
        "</urlset>"
    )
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    return app.send_static_file("robots.txt")


@app.route("/health")
def health():
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    txt = PARK_AVENUE_GUIDELINE_TXT.exists()
    return Response(
        f"ok\nGOOGLE_API_KEY set: {bool(api_key)}\npark_avenue.txt: {txt}",
        mimetype="text/plain",
    )


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
        logging.exception("Review failed")
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


@app.route("/apply", methods=["GET", "POST"])
def apply():
    if request.method == "GET":
        return render_template("apply.html")

    is_park_avenue = request.form.get("is_park_avenue") == "true"
    project_type = request.form.get("project_type", "").strip()
    project_description = request.form.get("project_description", "").strip()

    if not project_type:
        flash("Please select a project type.")
        return redirect(url_for("apply"))

    owns_guideline_temp = False
    guideline_path = None

    if is_park_avenue:
        if PARK_AVENUE_GUIDELINE_TXT.exists():
            guideline_path = str(PARK_AVENUE_GUIDELINE)
        elif PARK_AVENUE_GUIDELINE.exists():
            guideline_path = str(PARK_AVENUE_GUIDELINE)
        else:
            flash("The Park Avenue HOA guideline is not set up on this server yet.")
            return redirect(url_for("apply"))
    else:
        guideline_file = request.files.get("guideline_pdf")
        if not guideline_file or not guideline_file.filename:
            flash("Please upload the HOA guideline PDF.")
            return redirect(url_for("apply"))
        if not _is_pdf(guideline_file):
            flash("The HOA guideline file does not appear to be a valid PDF.")
            return redirect(url_for("apply"))
        guideline_fd, guideline_path = tempfile.mkstemp(suffix=".pdf")
        os.close(guideline_fd)
        guideline_file.save(guideline_path)
        owns_guideline_temp = True

    try:
        guidance = get_application_guidance(
            Path(guideline_path) if guideline_path else None,
            project_type,
            project_description,
            is_park_avenue=is_park_avenue,
        )
    except Exception as exc:
        logging.exception("Apply guidance failed")
        flash(f"Error: {exc}")
        return redirect(url_for("apply"))
    finally:
        if owns_guideline_temp and guideline_path:
            try:
                os.unlink(guideline_path)
            except OSError:
                pass

    return render_template("apply_result.html", guidance=guidance)


@app.route("/extract-project-types", methods=["POST"])
def extract_types():
    guideline_file = request.files.get("guideline_pdf")
    if not guideline_file or not guideline_file.filename:
        return jsonify({"error": "No guideline PDF uploaded."}), 400
    if not _is_pdf(guideline_file):
        return jsonify({"error": "File does not appear to be a valid PDF."}), 400

    guideline_fd, guideline_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.close(guideline_fd)
        guideline_file.save(guideline_path)
        result = extract_project_types(Path(guideline_path))
    except Exception as exc:
        logging.exception("extract_project_types failed")
        return jsonify({"error": str(exc)}), 500
    finally:
        try:
            os.unlink(guideline_path)
        except OSError:
            pass

    return jsonify(result)


@app.route("/generate-application", methods=["POST"])
def generate_application():
    try:
        guidance = json.loads(request.form.get("guidance_json", "{}"))
        applicant = {
            "name": request.form.get("name", ""),
            "email": request.form.get("email", ""),
            "phone": request.form.get("phone", ""),
            "mailing_address": request.form.get("mailing_address", ""),
            "property_address": request.form.get("property_address", ""),
            "project_description": request.form.get("project_description", ""),
        }
        pdf_bytes = generate_arc_application(guidance, applicant)
        filename = f"ARC_Application_{applicant['name'].replace(' ', '_') or 'Application'}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as exc:
        logging.exception("PDF generation failed")
        flash(f"Could not generate PDF: {exc}")
        return redirect(url_for("apply"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HOA/ARC review web app.")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug, host="0.0.0.0", port=args.port)
