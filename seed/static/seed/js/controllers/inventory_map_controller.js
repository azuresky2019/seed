/**
 * :copyright (c) 2014 - 2018, The Regents of the University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Department of Energy) and contributors. All rights reserved.
 * :author
 */
angular.module('BE.seed.controller.inventory_map', [])
  .controller('inventory_map_controller', [
    '$scope',
    '$stateParams',
    'inventory',
    'urls',
    'spinner_utility',
    function ($scope,
              $stateParams,
              inventory,
              urls,
              spinner_utility) {
      spinner_utility.show();

      $scope.inventory_type = $stateParams.inventory_type;
      $scope.data = inventory.results;
      $scope.pagination = inventory.pagination;

      // Render Map
      var renderMap = function () {
        var raster = new ol.layer.Tile({
          source: new ol.source.OSM()
        });

        // This will be done using iterations where WKT will be taken
        // from each property/taxlot entry
        var format = new ol.format.WKT();

        var wkt = 'POINT(-104.9862 39.765566)';
        var feature = format.readFeature(wkt, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857'
        });

        var wkt_two = 'POINT(-100.9862 39.765566)';
        var feature_two = format.readFeature(wkt_two, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857'
        });

        var vector_sources = new ol.source.Vector({
          features: [feature, feature_two]
        });

        var vector_style = new ol.style.Style({
          image: new ol.style.Icon({
            src: urls.static_url + "seed/images/favicon.ico",
            scale: 0.3,
            anchor: [0.5, 1]
          })
        });

        var vectors = new ol.layer.Vector({
          source: vector_sources,
          style: vector_style
        });

        // Consider making center be the centroid of points above
        // and zoom be dynamic (just large enough to see all points)
        center_zoom = {
          center: ol.proj.fromLonLat([-104.986292, 39.765566]),
          zoom: 4
        };

        var map = new ol.Map({
          target: 'map',
          layers: [raster, vectors],
          view: new ol.View(center_zoom)
        });
      };

      renderMap();

    }]);
