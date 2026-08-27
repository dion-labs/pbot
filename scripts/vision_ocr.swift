#!/usr/bin/env swift

import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: vision_ocr.swift IMAGE\n".utf8))
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard
    let image = NSImage(contentsOf: imageURL),
    let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write(Data("unable to read image\n".utf8))
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["en-US"]

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try handler.perform([request])

let width = CGFloat(cgImage.width)
let height = CGFloat(cgImage.height)
let observations = (request.results ?? []).compactMap { observation -> [String: Any]? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return [
        "text": candidate.string,
        "confidence": candidate.confidence,
        "x": Int((box.minX * width).rounded()),
        "y": Int(((1 - box.maxY) * height).rounded()),
        "width": Int((box.width * width).rounded()),
        "height": Int((box.height * height).rounded()),
    ]
}

let output: [String: Any] = [
    "image_width": cgImage.width,
    "image_height": cgImage.height,
    "observations": observations,
]
let data = try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data("\n".utf8))
