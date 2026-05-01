import AppKit

func pickFont(_ size: CGFloat) -> NSFont {
    if let f = NSFont(name: "AvenirNext-DemiBold", size: size) { return f }
    if let f = NSFont(name: "ArialRoundedMTBold", size: size) { return f }
    return NSFont.systemFont(ofSize: size, weight: .heavy)
}

func drawN2O(size: Int, path: String) {
    let s = CGFloat(size)
    let image = NSImage(size: NSSize(width: s, height: s))
    image.lockFocus()

    let rect = NSRect(x: 0, y: 0, width: s, height: s)
    NSColor.black.setFill()
    NSBezierPath(roundedRect: rect, xRadius: s * 0.23, yRadius: s * 0.23).fill()

    // text metrics
    let mainFont = pickFont(s * 0.50)
    let subFont = pickFont(s * 0.19)

    let mainAttrs: [NSAttributedString.Key: Any] = [
        .font: mainFont,
        .foregroundColor: NSColor.white
    ]
    let subAttrs: [NSAttributedString.Key: Any] = [
        .font: subFont,
        .foregroundColor: NSColor.white
    ]

    let n = NSString(string: "N")
    let o = NSString(string: "O")
    let two = NSString(string: "2")

    let nSize = n.size(withAttributes: mainAttrs)
    let oSize = o.size(withAttributes: mainAttrs)
    let twoSize = two.size(withAttributes: subAttrs)

    // Chemical formula geometry:
    // N and O share the same baseline; subscript 2 attaches to N lower-right.
    let nToO = s * 0.16
    let total = nSize.width + nToO + oSize.width
    let startX = (s - total) / 2
    let baseY = (s - nSize.height) / 2 + s * 0.01

    guard let ctx = NSGraphicsContext.current?.cgContext else { image.unlockFocus(); return }
    ctx.saveGState()
    // apply italic shear to create slanted style with rounded letter edges
    let shear = CGAffineTransform(a: 1, b: 0, c: 0.18, d: 1, tx: -s * 0.08, ty: 0)
    ctx.concatenate(shear)

    n.draw(at: NSPoint(x: startX, y: baseY), withAttributes: mainAttrs)
    let twoX = startX + nSize.width - (twoSize.width * 0.62)
    let twoY = baseY - (nSize.height * 0.07)
    two.draw(at: NSPoint(x: twoX, y: twoY), withAttributes: subAttrs)
    let oX = startX + nSize.width + nToO
    o.draw(at: NSPoint(x: oX, y: baseY), withAttributes: mainAttrs)

    ctx.restoreGState()
    image.unlockFocus()

    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { return }
    try? png.write(to: URL(fileURLWithPath: path))
}

let out = CommandLine.arguments[1]
let specs: [(Int, String)] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png")
]
for (size, name) in specs {
    drawN2O(size: size, path: "\(out)/\(name)")
}
