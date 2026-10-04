import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * Kalıcı ayarlar. Depolama erişimi her zaman hata verebilir (temizlenmiş
 * uygulama verisi, kısıtlı profil); bu yüzden her okuma/yazma sarmalanır ve
 * başarısızlıkta uygulama varsayılanlarla çalışmaya devam eder.
 */

const KEYS = {
  apiUrl: 'kitapai.apiUrl',
  apiKey: 'kitapai.apiKey',
  read: 'kitapai.read',
  theme: 'kitapai.theme',
} as const;

export interface ReadEntry {
  work_key: string;
  title: string;
}

export async function loadString(key: keyof typeof KEYS): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(KEYS[key]);
  } catch {
    return null;
  }
}

export async function saveString(key: keyof typeof KEYS, value: string): Promise<void> {
  try {
    await AsyncStorage.setItem(KEYS[key], value);
  } catch {
    // yok say — kalıcılık en iyi çabayla
  }
}

export async function loadRead(): Promise<ReadEntry[]> {
  const raw = await loadString('read');
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ReadEntry[]) : [];
  } catch {
    return [];
  }
}

export async function saveRead(entries: ReadEntry[]): Promise<void> {
  await saveString('read', JSON.stringify(entries));
}
