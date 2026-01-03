PYTHON ?= python3
VERSION ?= 0.1.3

release:
	$(PYTHON) - <<'PY'
	from pathlib import Path
	version = "$(VERSION)"
	path = Path("pyproject.toml")
	text = path.read_text()
	old = None
	for line in text.splitlines():
	    if line.startswith("version = "):
	        old = line
	        break
	if not old:
	    raise SystemExit("version not found in pyproject.toml")
	new = f'version = "{version}"'
	path.write_text(text.replace(old, new, 1))
	PY
	git add pyproject.toml
	git commit -m "Release v$(VERSION)"
	git tag v$(VERSION)
	git push origin main v$(VERSION)
	@echo "Released v$(VERSION)"

test:
	$(PYTHON) -m pytest -q
