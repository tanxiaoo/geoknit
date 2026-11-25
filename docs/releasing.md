# Releasing GeoKnit

A release is a tag `vX.Y.Z` equal to `geoknit.__version__`. Pushing it runs
`.github/workflows/release.yml`, which:

1. builds the frontend, the sdist and the wheel (`package.yml`);
2. installs the wheel into fresh environments on Windows and Ubuntu (Python
   3.11 and 3.12) and runs `scripts/smoke_test.py`;
3. uploads to PyPI with trusted publishing (no API tokens);
4. creates the GitHub release with the wheel and sdist attached.

Running the workflow by hand (Actions → Release → Run workflow) does steps 1–2
and uploads to **TestPyPI** instead: a dry run.

## One-time setup

Trusted publishing lets the workflow upload without a stored token. Set it up
once on each index:

1. **PyPI** (https://pypi.org/manage/account/publishing/): add a *pending
   publisher* — PyPI project name `geoknit`, owner `tanxiaoo`, repository
   `geoknit`, workflow `release.yml`, environment `pypi`.
2. **TestPyPI** (https://test.pypi.org/manage/account/publishing/, a separate
   account): the same, with environment `testpypi`.
3. **GitHub** (repository Settings → Environments): create the environments
   `pypi` and `testpypi`. Adding yourself as a required reviewer on `pypi`
   makes every real upload wait for your approval.

## Making a release

1. On `main`, set `__version__` in `geoknit/__init__.py` (e.g. `0.1.0`) and
   merge that change.
2. Optional dry run: Actions → Release → Run workflow on `main`; check
   https://test.pypi.org/project/geoknit/ and try
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ geoknit`.
3. Tag and push:

   ```bash
   git checkout main && git pull
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Approve the `pypi` deployment if you added a reviewer. When the workflow is
   green, `pip install geoknit` installs the new version and the GitHub
   release lists the files.

A version can be uploaded to PyPI only once. If something is wrong after the
upload, fix it and release the next version (`0.1.1`).

## Building locally

```bash
cd frontend && npm ci && npm run build && cd ..
python -m pip install build
python -m build                      # dist/geoknit-*.tar.gz and dist/geoknit-*.whl
python -m venv /tmp/gk && /tmp/gk/bin/pip install dist/geoknit-*.whl
/tmp/gk/bin/python scripts/smoke_test.py
```

On Windows, the venv's programs are in `Scripts\` instead of `bin/`.

Building a wheel without the frontend fails on purpose (`hatch_build.py`): a
wheel without `geoknit/server/static/` would only show a placeholder page. Set
`GEOKNIT_ALLOW_NO_FRONTEND=1` to build one anyway. Editable installs
(`pip install -e .`) are not affected.
