import SwiftUI

/// Web ve Android istemcileriyle aynı renk belirteçleri.
enum Palette {
    static func bg(_ dark: Bool) -> Color { dark ? hex(0x141210) : hex(0xF5F0E8) }
    static func surface(_ dark: Bool) -> Color { dark ? hex(0x221F1B) : .white }
    static func surface2(_ dark: Bool) -> Color { dark ? hex(0x1A1713) : hex(0xFDFAF5) }
    static func border(_ dark: Bool) -> Color { dark ? hex(0x35312A) : hex(0xD9D3C7) }
    static func text(_ dark: Bool) -> Color { dark ? hex(0xF0EBE0) : hex(0x1A1A18) }
    static func text2(_ dark: Bool) -> Color { dark ? hex(0x9A9080) : hex(0x6B6558) }
    static func accent(_ dark: Bool) -> Color { dark ? hex(0xD4845A) : hex(0xC96A2B) }
    static func tagBg(_ dark: Bool) -> Color { dark ? hex(0x2A2520) : hex(0xE8E0D0) }
    static func tagText(_ dark: Bool) -> Color { dark ? hex(0xB5A898) : hex(0x4A4035) }
    static func danger(_ dark: Bool) -> Color { dark ? hex(0xF2B8B5) : hex(0xB3261E) }

    static func hex(_ value: UInt32) -> Color {
        Color(
            red: Double((value >> 16) & 0xFF) / 255.0,
            green: Double((value >> 8) & 0xFF) / 255.0,
            blue: Double(value & 0xFF) / 255.0
        )
    }
}

/// Görünüm ağacında tekrar tekrar `colorScheme == .dark` yazmamak için.
struct ThemeKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var isDarkTheme: Bool {
        get { self[ThemeKey.self] }
        set { self[ThemeKey.self] = newValue }
    }
}
