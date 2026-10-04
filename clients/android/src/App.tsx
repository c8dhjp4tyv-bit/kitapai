import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import type {
  Book,
  RecommendRequest,
  RecommendResponse,
  TaxonomyResponse,
} from '@kitapai/shared';
import { ApiError } from '@kitapai/shared';
import { Chip } from './components/Chip';
import { BookCard } from './components/BookCard';
import { apiUrl, client, hydrate, setApiUrl } from './config';
import { loadRead, saveRead } from './storage';
import { dark, light } from './theme';

const EXAMPLES = [
  'çölde geçen, ağır olmayan epik bir bilim kurgu',
  'yas ve kayıp üzerine sakin bir roman',
  'metroda okumak için tırnak yediren bir polisiye',
];

export default function App() {
  const systemDark = useColorScheme() === 'dark';
  const [isDark, setIsDark] = useState(systemDark);
  const palette = isDark ? dark : light;

  const [taxonomy, setTaxonomy] = useState<TaxonomyResponse | null>(null);
  const [query, setQuery] = useState('');
  const [genres, setGenres] = useState<string[]>([]);
  const [moods, setMoods] = useState<string[]>([]);
  const [read, setRead] = useState<{ work_key: string; title: string }[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [serverInput, setServerInput] = useState(apiUrl());

  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTaxonomy = useCallback(() => {
    client()
      .taxonomy()
      .then((t) => {
        setTaxonomy(t);
        setError(null);
      })
      .catch(() => setError('Sunucuya ulaşılamadı. Tailscale açık mı?'));
  }, []);

  // Kayıtlı ayarlar yüklendikten *sonra* ilk istek atılır; aksi hâlde
  // varsayılan adrese boşuna gidilir.
  useEffect(() => {
    void (async () => {
      const url = await hydrate();
      setServerInput(url);
      setRead(await loadRead());
      loadTaxonomy();
    })();
  }, [loadTaxonomy]);

  useEffect(() => {
    void saveRead(read);
  }, [read]);

  const toggle = (list: string[], set: (v: string[]) => void) => (slug: string) =>
    set(list.includes(slug) ? list.filter((s) => s !== slug) : [...list, slug]);

  const run = useCallback(
    async (overrides: Partial<RecommendRequest> = {}) => {
      setLoading(true);
      setError(null);
      try {
        const response = await client().recommend({
          query,
          genres,
          moods,
          exclude_work_keys: read.map((r) => r.work_key),
          limit: 3,
          ...overrides,
        });
        setResult(response);
      } catch (err) {
        setError(err instanceof ApiError ? err.userMessage : String(err));
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [query, genres, moods, read],
  );

  const onToggleRead = useCallback((work_key: string, title: string) => {
    setRead((prev) =>
      prev.some((r) => r.work_key === work_key)
        ? prev.filter((r) => r.work_key !== work_key)
        : [...prev, { work_key, title }],
    );
  }, []);

  const onPickSimilar = useCallback(
    (book: Book) => {
      const next = `${book.title} gibi bir kitap`;
      setQuery(next);
      void run({ query: next, genres: [], moods: [] });
    },
    [run],
  );

  async function applyServer() {
    await setApiUrl(serverInput);
    setShowSettings(false);
    loadTaxonomy();
  }

  const readKeys = useMemo(() => new Set(read.map((r) => r.work_key)), [read]);

  return (
    <SafeAreaProvider>
      <SafeAreaView style={[styles.safe, { backgroundColor: palette.bg }]}>
        <StatusBar
          barStyle={isDark ? 'light-content' : 'dark-content'}
          backgroundColor={palette.surface}
        />
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={[styles.header, { borderBottomColor: palette.border }]}>
            <Text style={[styles.logo, { color: palette.text }]}>📖 kitap.ai</Text>
            <View style={styles.headerRight}>
              <TouchableOpacity
                onPress={() => setShowSettings((s) => !s)}
                style={[styles.pill, { borderColor: palette.border, backgroundColor: palette.tagBg }]}
              >
                <Text style={{ color: palette.text2, fontSize: 12 }}>sunucu</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => setIsDark((d) => !d)}
                style={[styles.pill, { borderColor: palette.border, backgroundColor: palette.tagBg }]}
              >
                <Text style={{ color: palette.text2, fontSize: 13 }}>{isDark ? '☀︎' : '☾'}</Text>
              </TouchableOpacity>
            </View>
          </View>

          {showSettings && (
            <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.border }]}>
              <Text style={[styles.label, { color: palette.text2 }]}>API ADRESİ</Text>
              <TextInput
                style={[
                  styles.serverInput,
                  { backgroundColor: palette.surface2, borderColor: palette.border, color: palette.text },
                ]}
                value={serverInput}
                onChangeText={setServerInput}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholder="http://100.x.y.z:8000"
                placeholderTextColor={palette.text2}
              />
              <Text style={[styles.small, { color: palette.text2 }]}>
                Tailscale IP'si ya da https://makine.tailnet.ts.net
              </Text>
              <TouchableOpacity
                style={[styles.submit, { backgroundColor: palette.accent }]}
                onPress={() => void applyServer()}
              >
                <Text style={styles.submitText}>Kaydet ve bağlan</Text>
              </TouchableOpacity>
            </View>
          )}

          <View style={styles.hero}>
            <Text style={[styles.heroTitle, { color: palette.text }]}>
              Sana özel{'\n'}
              <Text style={{ color: palette.accent, fontStyle: 'italic' }}>kitap önerileri</Text>
            </Text>
            <Text style={[styles.heroSub, { color: palette.text2 }]}>
              Ne aradığını kendi cümlelerinle yaz.
            </Text>
          </View>

          <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.border }]}>
            <Text style={[styles.label, { color: palette.text2 }]}>NE ARIYORSUN?</Text>
            <TextInput
              style={[
                styles.input,
                { backgroundColor: palette.surface2, borderColor: palette.border, color: palette.text },
              ]}
              placeholder="Konu, his, durum ya da benzediği kitap…"
              placeholderTextColor={palette.text2}
              value={query}
              onChangeText={setQuery}
              multiline
              maxLength={500}
            />

            <View style={styles.examples}>
              {EXAMPLES.map((ex) => (
                <TouchableOpacity key={ex} onPress={() => setQuery(ex)}>
                  <Text style={[styles.example, { color: palette.text2, borderColor: palette.border }]}>
                    {ex}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {taxonomy && (
              <>
                <Text style={[styles.label, { color: palette.text2, marginTop: 14 }]}>TÜR</Text>
                <View style={styles.chips}>
                  {taxonomy.genres.map((g) => (
                    <Chip
                      key={g.slug}
                      label={g.label}
                      active={genres.includes(g.slug)}
                      onPress={() => toggle(genres, setGenres)(g.slug)}
                      palette={palette}
                    />
                  ))}
                </View>

                <Text style={[styles.label, { color: palette.text2, marginTop: 6 }]}>RUH HALİ</Text>
                <View style={styles.chips}>
                  {taxonomy.moods.map((m) => (
                    <Chip
                      key={m.slug}
                      label={m.label}
                      active={moods.includes(m.slug)}
                      onPress={() => toggle(moods, setMoods)(m.slug)}
                      palette={palette}
                    />
                  ))}
                </View>
              </>
            )}

            {error && <Text style={[styles.error, { color: palette.danger }]}>{error}</Text>}

            <TouchableOpacity
              style={[styles.submit, { backgroundColor: palette.accent }, loading && { opacity: 0.6 }]}
              onPress={() => void run()}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.submitText}>Kitap Öner →</Text>
              )}
            </TouchableOpacity>

            {read.length > 0 && (
              <Text style={[styles.small, { color: palette.text2 }]}>
                {read.length} okunmuş kitap önerilerden çıkarılıyor
              </Text>
            )}
          </View>

          {result && (
            <View style={styles.results}>
              <Text style={[styles.resultsTitle, { color: palette.text }]}>Öneriler</Text>
              {result.recommendations.length === 0 && (
                <Text style={{ color: palette.text2 }}>
                  Bu kısıtlara uyan kitap bulunamadı. Filtreleri gevşetmeyi dene.
                </Text>
              )}
              {result.recommendations.map((rec) => (
                <BookCard
                  key={rec.book.work_key}
                  recommendation={rec}
                  taxonomy={taxonomy}
                  palette={palette}
                  isRead={readKeys.has(rec.book.work_key)}
                  onToggleRead={onToggleRead}
                  onPickSimilar={onPickSimilar}
                />
              ))}
              {result.followups.map((f) => (
                <Text key={f} style={[styles.followup, { color: palette.text2 }]}>
                  {f}
                </Text>
              ))}
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingBottom: 60 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerRight: { flexDirection: 'row', gap: 8 },
  logo: { fontSize: 18, fontWeight: '600' },
  pill: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  hero: { alignItems: 'center', paddingHorizontal: 24, paddingTop: 34, paddingBottom: 20 },
  heroTitle: { fontSize: 30, fontWeight: '700', textAlign: 'center', lineHeight: 38 },
  heroSub: { fontSize: 14, textAlign: 'center', marginTop: 8 },
  card: { marginHorizontal: 14, marginBottom: 14, borderRadius: 16, padding: 18, borderWidth: 1 },
  label: { fontSize: 11, fontWeight: '600', letterSpacing: 0.6, marginBottom: 8 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    fontSize: 14,
    minHeight: 76,
    textAlignVertical: 'top',
  },
  examples: { marginTop: 10, gap: 6 },
  example: { fontSize: 12, borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap' },
  submit: { borderRadius: 12, padding: 15, alignItems: 'center', marginTop: 14 },
  submitText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  error: { fontSize: 13, marginTop: 10 },
  small: { fontSize: 12, marginTop: 10 },
  serverInput: { borderWidth: 1, borderRadius: 10, padding: 12, fontSize: 14 },
  results: { paddingHorizontal: 14 },
  resultsTitle: { fontSize: 20, fontWeight: '700', marginBottom: 12 },
  followup: { fontSize: 13, fontStyle: 'italic', marginTop: 6 },
});
