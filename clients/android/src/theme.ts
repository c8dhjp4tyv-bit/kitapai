/** Web istemcisiyle aynı renk belirteçleri. */

export const light = {
  bg: '#F5F0E8',
  surface: '#FFFFFF',
  surface2: '#FDFAF5',
  border: '#D9D3C7',
  text: '#1A1A18',
  text2: '#6B6558',
  accent: '#C96A2B',
  accentSoft: 'rgba(201,106,43,0.12)',
  tagBg: '#E8E0D0',
  tagText: '#4A4035',
  danger: '#B3261E',
};

export const dark: typeof light = {
  bg: '#141210',
  surface: '#221F1B',
  surface2: '#1A1713',
  border: '#35312A',
  text: '#F0EBE0',
  text2: '#9A9080',
  accent: '#D4845A',
  accentSoft: 'rgba(212,132,90,0.16)',
  tagBg: '#2A2520',
  tagText: '#B5A898',
  danger: '#F2B8B5',
};

export type Palette = typeof light;
