import "./style.css";

import { Map } from "maplibre-gl";

const baseUrl =
  window.location.origin +
  window.location.pathname.substring(
    0,
    window.location.pathname.lastIndexOf("/"),
  );

const toAbsolute = (url) => {
  if (!url || url.indexOf("://") >= 0) {
    return url;
  }

  if (url.startsWith("./")) {
    return baseUrl + "/" + url.substring(2);
  } else if (url.startsWith("../")) {
    const parts = baseUrl.split("/");
    let urlParts = url.split("/");
    while (urlParts[0] === "..") {
      parts.pop();
      urlParts.shift();
    }
    return parts.join("/") + "/" + urlParts.join("/");
  } else if (!url.startsWith("/")) {
    return baseUrl + "/" + url;
  } else {
    return window.location.origin + url;
  }
};

const map = new Map({
  container: "map",
  center: [7.420573260138943, 43.73687264886423],
  zoom: 11,
  transformRequest: (url) => {
    return { url: toAbsolute(url) };
  },
});

map.setStyle("./styles/liberty", {
  validate: false,
  transformStyle: (previousStyle, nextStyle) => {
    return {
      ...nextStyle,
      glyphs: toAbsolute(nextStyle.glyphs),
      sprite: toAbsolute(nextStyle.sprite),
      sources: Object.fromEntries(
        Object.entries(nextStyle.sources || {}).map(([key, source]) => {
          const updatedSource = { ...source };

          if (source.url) {
            updatedSource.url = toAbsolute(source.url);
          }

          if (source.tiles && Array.isArray(source.tiles)) {
            updatedSource.tiles = source.tiles.map(toAbsolute);
          }

          if (source.data && typeof source.data === "string") {
            updatedSource.data = toAbsolute(source.data);
          }

          return [key, updatedSource];
        }),
      ),
    };
  },
});
