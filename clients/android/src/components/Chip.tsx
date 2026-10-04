import React from 'react';
import { StyleSheet, Text, TouchableOpacity } from 'react-native';
import type { Palette } from '../theme';

interface Props {
  label: string;
  active?: boolean;
  onPress: () => void;
  palette: Palette;
}

export function Chip({ label, active, onPress, palette }: Props) {
  return (
    <TouchableOpacity
      accessibilityRole="button"
      accessibilityState={{ selected: !!active }}
      onPress={onPress}
      style={[
        styles.chip,
        {
          backgroundColor: active ? palette.accent : palette.tagBg,
          borderColor: active ? palette.accent : palette.border,
        },
      ]}
    >
      <Text style={[styles.text, { color: active ? '#fff' : palette.tagText }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  chip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 13,
    paddingVertical: 7,
    marginRight: 8,
    marginBottom: 8,
  },
  text: { fontSize: 13 },
});
