import React, { useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import type { Book, Recommendation, TaxonomyResponse } from '@kitapai/shared';
import { client } from '../config';
import type { Palette } from '../theme';

interface Props {
  recommendation: Recommendation;
  taxonomy: TaxonomyResponse | null;
  palette: Palette;
  isRead: boolean;
  onToggleRead: (workKey: string, title: string) => void;
  onPickSimilar: (book: Book) => void;
}

function labelOf(taxonomy: TaxonomyResponse | null, kind: 'genres' | 'moods', slug: string) {
  return taxonomy?.[kind].find((e) => e.slug === slug)?.label ?? slug;
}

export function BookCard({
  recommendation,
  taxonomy,
  palette,
  isRead,
  onToggleRead,
  onPickSimilar,
}: Props) {
  const { book, why, hooks, content_notes, confidence, rank } = recommendation;
  const [similar, setSimilar] = useState<Book[] | null>(null);
  const [loading, setLoading] = useState(false);

  const meta = [
    book.authors.join(', '),
    book.first_published ? String(book.first_published) : '',
    book.pages ? `${book.pages} sayfa` : '',
    book.rating ? `★ ${book.rating.average.toFixed(1)}` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  async function loadSimilar() {
    if (similar) {
      setSimilar(null);
      return;
    }
    setLoading(true);
    try {
      const res = await client().similar(book.work_key, 6);
      setSimilar(res.books);
    } catch {
      setSimilar([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={[styles.card, { backgroundColor: palette.surface, borderColor: palette.border }]}>
      <View style={styles.head}>
        {book.cover_url ? (
          <Image source={{ uri: book.cover_url }} style={styles.cover} />
        ) : (
          <View style={[styles.cover, styles.coverEmpty, { backgroundColor: palette.tagBg }]}>
            <Text style={{ fontSize: 26 }}>📖</Text>
          </View>
        )}
        <View style={styles.headText}>
          <Text style={[styles.rank, { color: palette.accent }]}>ÖNERİ {rank}</Text>
          <Text style={[styles.title, { color: palette.text }]}>{book.title}</Text>
          <Text style={[styles.meta, { color: palette.text2 }]}>{meta}</Text>
          <View style={styles.tags}>
            {book.genres.slice(0, 3).map((g) => (
              <View key={g} style={[styles.tag, { backgroundColor: palette.tagBg }]}>
                <Text style={[styles.tagText, { color: palette.tagText }]}>
                  {labelOf(taxonomy, 'genres', g)}
                </Text>
              </View>
            ))}
            {book.moods.slice(0, 2).map((m) => (
              <View key={m} style={[styles.tag, { backgroundColor: palette.accentSoft }]}>
                <Text style={[styles.tagText, { color: palette.accent }]}>
                  {labelOf(taxonomy, 'moods', m)}
                </Text>
              </View>
            ))}
          </View>
        </View>
      </View>

      <Text style={[styles.why, { color: palette.text }]}>{why}</Text>

      {hooks.length > 0 && (
        <Text style={[styles.hooks, { color: palette.text2 }]}>{hooks.join(' · ')}</Text>
      )}

      {content_notes.length > 0 && (
        <Text style={[styles.notes, { color: palette.danger }]}>
          İçerik uyarısı: {content_notes.join(', ')}
        </Text>
      )}

      <View style={[styles.confidence, { backgroundColor: palette.tagBg }]}>
        <View
          style={[
            styles.confidenceBar,
            { backgroundColor: palette.accent, width: `${Math.round(confidence * 100)}%` },
          ]}
        />
      </View>

      <View style={styles.actions}>
        <TouchableOpacity
          style={[styles.action, { borderColor: palette.border }]}
          onPress={() => Linking.openURL(book.openlibrary_url)}
        >
          <Text style={{ color: palette.text2, fontSize: 13 }}>Open Library</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.action, { borderColor: palette.border }]}
          onPress={loadSimilar}
        >
          {loading ? (
            <ActivityIndicator size="small" color={palette.accent} />
          ) : (
            <Text style={{ color: palette.text2, fontSize: 13 }}>
              {similar ? 'Benzerleri gizle' : 'Benzerleri'}
            </Text>
          )}
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.action, { borderColor: isRead ? palette.accent : palette.border }]}
          onPress={() => onToggleRead(book.work_key, book.title)}
        >
          <Text style={{ color: isRead ? palette.accent : palette.text2, fontSize: 13 }}>
            {isRead ? '✓ Okudum' : 'Okudum'}
          </Text>
        </TouchableOpacity>
      </View>

      {similar && similar.length > 0 && (
        <View style={styles.similar}>
          {similar.map((s) => (
            <TouchableOpacity key={s.work_key} onPress={() => onPickSimilar(s)} style={styles.similarItem}>
              {s.cover_url && <Image source={{ uri: s.cover_url }} style={styles.similarCover} />}
              <Text numberOfLines={2} style={{ color: palette.text2, fontSize: 11 }}>
                {s.title}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 16, padding: 18, marginBottom: 14 },
  head: { flexDirection: 'row', gap: 14, marginBottom: 12 },
  cover: { width: 70, height: 104, borderRadius: 6 },
  coverEmpty: { alignItems: 'center', justifyContent: 'center' },
  headText: { flex: 1 },
  rank: { fontSize: 11, fontWeight: '600', letterSpacing: 0.6 },
  title: { fontSize: 18, fontWeight: '700', marginTop: 2, marginBottom: 3 },
  meta: { fontSize: 13, marginBottom: 8 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  tagText: { fontSize: 11, fontWeight: '600' },
  why: { fontSize: 14, lineHeight: 21, marginBottom: 10 },
  hooks: { fontSize: 12, marginBottom: 10 },
  notes: { fontSize: 12, marginBottom: 10 },
  confidence: { height: 3, borderRadius: 2, overflow: 'hidden' },
  confidenceBar: { height: 3 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  action: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  similar: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 12 },
  similarItem: { width: 84 },
  similarCover: { width: 84, height: 122, borderRadius: 4, marginBottom: 4 },
});
