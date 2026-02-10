# maps2zim

This scrapers creates an offline maps, based on [OpenStreetMap](https://www.openstreetmap.org/) data, in the ZIM format.

[![CodeFactor](https://www.codefactor.io/repository/github/openzim/maps/badge)](https://www.codefactor.io/repository/github/openzim/maps)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![codecov](https://codecov.io/gh/openzim/maps/branch/main/graph/badge.svg)](https://codecov.io/gh/openzim/maps)
[![PyPI version shields.io](https://img.shields.io/pypi/v/maps2zim.svg)](https://pypi.org/project/maps2zim/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/maps2zim.svg)](https://pypi.org/project/maps2zim)
[![Docker](https://ghcr-badge.egpl.dev/openzim/maps/latest_tag?label=docker)](https://ghcr.io/openzim/maps)

## Installation

There are three main ways to install and use `maps2zim` from most recommended to least:

<details>
<summary>Install using a pre-built container</summary>

1. Download the image using `docker`:

   ```sh
   docker pull ghcr.io/openzim/maps
   ```

</details>
<details>
<summary>Build your own container</summary>

1. Clone the repository locally:

   ```sh
   git clone https://github.com/openzim/maps.git && cd maps
   ```

1. Build the image:

   ```sh
   docker build -t ghcr.io/openzim/maps .
   ```

</details>
<details>
<summary>Run the software locally using Hatch</summary>

1. Clone the repository locally:

   ```sh
   git clone https://github.com/openzim/maps.git && cd maps
   ```

1. Install [Hatch](https://hatch.pypa.io/):

   ```sh
   pip3 install hatch
   ```

1. Start a hatch shell to install software and dependencies in an isolated virtual environment.

   ```sh
   hatch shell
   ```

1. Run the `maps2zim` command:

   ```sh
   maps2zim --help
   ```

</details>

## Usage

```sh
# Get help
docker run -v output:/output ghcr.io/openzim/maps maps2zim --help
```

TODO: add correct sample command below

```sh
# Create a ZIM for ...
docker run -v output:/output ghcr.io/openzim/maps maps2zim ???
```

## Developing

Use the commands below to set up the project once:

```sh
# Install hatch if it isn't installed already.
❯ pip install hatch

# Local install (in default env) / re-sync packages
❯ hatch run pip list

# Set-up pre-commit
❯ pre-commit install
```

The following commands can be used to build and test the scraper:

```sh
# Show scripts
❯ hatch env show

# linting, testing, coverage, checking
❯ hatch run lint:all
❯ hatch run lint:fixall

# run tests on all matrixed' envs
❯ hatch run test:run

# run tests in a single matrixed' env
❯ hatch env run -e test -i py=3.12 coverage

# run static type checks
❯ hatch env run check:all

# building packages
❯ hatch build
```

### Contributing

This project adheres to openZIM's [Contribution Guidelines](https://github.com/openzim/overview/wiki/Contributing).

This project has implemented openZIM's [Python bootstrap, conventions and policies](https://github.com/openzim/_python-bootstrap/blob/main/docs/Policy.md) **v1.0.3**.

See details for contributions in [CONTRIBUTING.md](CONTRIBUTING.md).
