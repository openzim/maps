# maps2zim-poc
PoC on having a ZIM with maps inside

## Prerequisites

- OSM tiles generated locally (done with https://github.com/Magellium/osmtilemaker for the PoC, simply follow the README)
- Python 3.13

## How it was built

Create a Node.JS Vite app with ol package:

```
npm create ol-app ol-app
```

Tweak few things:
- adjust CSS + HTML to display a title with the map
- adjust JS to load tiles locally instead of OSM online tile server
- adjust `vite.config.js` to specify base directory

## Python setup

Create your venv and install requirements

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements
```

## Usage

Build Vite app:

```
cd ol-app
npm run build
cd ..
```

Create the ZIM

```bash
python create-zim.py
```

## Example
An example of ZIM is available for download [here](https://tmp.kiwix.org/zims/tests_maps2zim_switzerland.zim).
