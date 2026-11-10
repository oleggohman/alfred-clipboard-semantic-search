// Renders workflow/icon.png: clipboard + LLM sparkles. Usage: swift scripts/make_icon.swift workflow/icon.png [size]
import AppKit
import CoreGraphics

let args = CommandLine.arguments
let outPath = args.count > 1 ? args[1] : "icon.png"
let S = CGFloat(args.count > 2 ? Double(args[2])! : 512)
let px = Int(S)

let cs = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: px, height: px, bitsPerComponent: 8, bytesPerRow: 0,
                          space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { fatalError("ctx") }
// Work in a 512 unit space, origin bottom-left.
ctx.scaleBy(x: S / 512, y: S / 512)

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
    CGColor(colorSpace: cs, components: [r / 255, g / 255, b / 255, a])!
}

// Background: rounded square with violet -> indigo gradient.
let bg = CGRect(x: 24, y: 24, width: 464, height: 464)
let bgPath = CGPath(roundedRect: bg, cornerWidth: 104, cornerHeight: 104, transform: nil)
ctx.saveGState()
ctx.addPath(bgPath); ctx.clip()
let bgGrad = CGGradient(colorsSpace: cs, colors: [rgb(124, 58, 237), rgb(67, 56, 202)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bgGrad, start: CGPoint(x: 24, y: 488), end: CGPoint(x: 488, y: 24), options: [])
ctx.restoreGState()

// Clipboard board with soft shadow.
let board = CGRect(x: 120, y: 72, width: 272, height: 340)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -10), blur: 24, color: rgb(20, 10, 60, 0.45))
ctx.addPath(CGPath(roundedRect: board, cornerWidth: 34, cornerHeight: 34, transform: nil))
ctx.setFillColor(rgb(255, 255, 255)); ctx.fillPath()
ctx.restoreGState()

// Clip at the top.
let clipOuter = CGRect(x: 186, y: 380, width: 140, height: 64)
ctx.addPath(CGPath(roundedRect: clipOuter, cornerWidth: 22, cornerHeight: 22, transform: nil))
ctx.setFillColor(rgb(49, 46, 129)); ctx.fillPath()
let clipHole = CGRect(x: 236, y: 418, width: 40, height: 14)
ctx.addPath(CGPath(roundedRect: clipHole, cornerWidth: 7, cornerHeight: 7, transform: nil))
ctx.setFillColor(rgb(124, 58, 237)); ctx.fillPath()

// Four-point sparkle path centred at c with radius r.
func sparkle(_ c: CGPoint, _ r: CGFloat) -> CGPath {
    let p = CGMutablePath()
    let k = r * 0.16   // waist control: smaller = sharper points
    p.move(to: CGPoint(x: c.x, y: c.y + r))
    p.addQuadCurve(to: CGPoint(x: c.x + r, y: c.y), control: CGPoint(x: c.x + k, y: c.y + k))
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r), control: CGPoint(x: c.x + k, y: c.y - k))
    p.addQuadCurve(to: CGPoint(x: c.x - r, y: c.y), control: CGPoint(x: c.x - k, y: c.y - k))
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: CGPoint(x: c.x - k, y: c.y + k))
    p.closeSubpath()
    return p
}

// Sparkles filled with the brand gradient.
let sparkles = CGMutablePath()
sparkles.addPath(sparkle(CGPoint(x: 236, y: 262), 82))
sparkles.addPath(sparkle(CGPoint(x: 326, y: 330), 36))
sparkles.addPath(sparkle(CGPoint(x: 322, y: 206), 22))
ctx.saveGState()
ctx.addPath(sparkles); ctx.clip()
let spGrad = CGGradient(colorsSpace: cs, colors: [rgb(168, 85, 247), rgb(79, 70, 229)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(spGrad, start: CGPoint(x: 150, y: 350), end: CGPoint(x: 360, y: 180), options: [])
ctx.restoreGState()

// Text lines at the bottom of the page.
ctx.setFillColor(rgb(203, 213, 225))
for (y, w) in [(140.0, 192.0), (104.0, 132.0)] {
    ctx.addPath(CGPath(roundedRect: CGRect(x: 160, y: y, width: w, height: 16), cornerWidth: 8, cornerHeight: 8, transform: nil))
    ctx.fillPath()
}

guard let img = ctx.makeImage() else { fatalError("image") }
let rep = NSBitmapImageRep(cgImage: img)
guard let data = rep.representation(using: .png, properties: [:]) else { fatalError("png") }
try! data.write(to: URL(fileURLWithPath: outPath))
print("wrote \(outPath) \(px)x\(px)")
