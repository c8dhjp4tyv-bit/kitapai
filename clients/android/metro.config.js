const path = require('node:path');
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

// Ortak API sözleşmesi (`clients/shared`) proje kökünün dışında duruyor.
// Metro yalnızca kendi kökünü izlediği için hem watchFolders'a eklenir hem de
// modül adı doğrudan kaynağa çözümlenir — böylece web ve Android aynı dosyayı
// kullanır, kopya tutulmaz.
const sharedRoot = path.resolve(__dirname, '../shared');

const config = {
  watchFolders: [sharedRoot],
  resolver: {
    extraNodeModules: {
      '@kitapai/shared': sharedRoot,
    },
  },
};

module.exports = mergeConfig(getDefaultConfig(__dirname), config);
