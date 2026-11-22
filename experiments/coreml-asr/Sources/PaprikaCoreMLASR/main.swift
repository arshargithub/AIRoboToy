import Foundation
import CoreML
import WhisperKit

// No networking in the inference process, including automatic Hub fallbacks.
final class OfflineProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool {
        return ["https", "http"].contains(request.url?.scheme ?? "")
    }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        client?.urlProtocol(self, didFailWithError: NSError(domain: "PaprikaOffline", code: 1))
    }
    override func stopLoading() {}
}

func emit(_ value: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}
func finite(_ value: Float) -> Any { value.isFinite ? Double(value) : NSNull() }

@main struct Worker {
    static func main() async throws {
        URLProtocol.registerClass(OfflineProtocol.self)
        let args=CommandLine.arguments
        guard args.count == 3 || (args.count == 4 && args[3] == "names") else { throw NSError(domain:"PaprikaArguments",code:1) }
        let namesHint = args.count == 4
        let root=URL(fileURLWithPath:args[1],isDirectory:true)
        let useGPU=args[2]=="gpu"
        let decoderGPU=args[2]=="ane-gpu"
        let tokenizer=root.appendingPathComponent("tokenizer")
        guard FileManager.default.fileExists(atPath:tokenizer.appendingPathComponent("tokenizer.json").path),
              FileManager.default.fileExists(atPath:tokenizer.appendingPathComponent("tokenizer_config.json").path)
        else { throw NSError(domain:"PaprikaTokenizerMissing",code:1) }
        let compute=ModelComputeOptions(melCompute:.cpuAndGPU,
            audioEncoderCompute:useGPU ? .cpuAndGPU : .cpuAndNeuralEngine,
            textDecoderCompute:decoderGPU ? .cpuAndGPU : .cpuAndNeuralEngine)
        let config=WhisperKitConfig(model:"large-v3-turbo",modelFolder:root.path,
            tokenizerFolder:tokenizer,computeOptions:compute,verbose:false,
            prewarm:true,load:true,download:false)
        let kit=try await WhisperKit(config)
        guard let tokenizerModel=kit.tokenizer else { throw NSError(domain:"PaprikaTokenizerMissing",code:2) }
        let prompt:String? = namesHint ? "Names: Tavi, Paprika." : nil
        let generation=try JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("generation_config.json"))) as! [String:Any]
        let suppress=generation["suppress_tokens"] as? [Int] ?? []
        let options=DecodingOptions(verbose:false,task:.transcribe,language:"en",temperature:0,
            temperatureFallbackCount:0,topK:1,usePrefillPrompt:true,detectLanguage:false,
            skipSpecialTokens:true,withoutTimestamps:false,wordTimestamps:false,
            windowClipTime:0,promptTokens:prompt.map { tokenizerModel.encode(text:$0) },prefixTokens:nil,suppressBlank:true,
            suppressTokens:suppress,firstTokenLogProbThreshold:nil,concurrentWorkerCount:1)
        try emit(["ready":true,"protocol":1,"profile":["engine":"WhisperKit","version":"1.1.1",
            "model":"large-v3-turbo","compute_type":"float16","language":"en",
            "encoder_compute_requested":useGPU ? "CPU/GPU" : "CPU/NeuralEngine",
            "decoder_compute_requested":decoderGPU ? "CPU/GPU" : "CPU/NeuralEngine","prompt":prompt as Any? ?? NSNull(),"network":"disabled"]])
        while let line=readLine() {
            guard line.utf8.count<900000,let data=line.data(using:.utf8),
                  let r=try JSONSerialization.jsonObject(with:data) as? [String:Any],
                  let id=r["id"] as? String,let encoded=r["pcm"] as? String,
                  let pcm=Data(base64Encoded:encoded),pcm.count>0,pcm.count<=640000,pcm.count%2==0
            else { return }
            do {
                let samples:[Float]=pcm.withUnsafeBytes { raw in
                    stride(from:0,to:pcm.count,by:2).map { offset in
                        Float(Int16(littleEndian:raw.loadUnaligned(fromByteOffset:offset,as:Int16.self)))/32768
                    }
                }
                let began=ProcessInfo.processInfo.systemUptime
                let result=try await kit.transcribe(audioArray:samples,decodeOptions:options)
                let ms=(ProcessInfo.processInfo.systemUptime-began)*1000
                let segments=result.flatMap(\.segments)
                let scores:[[String:Any]]=segments.prefix(64).map { s in
                    ["start":finite(s.start),"end":finite(s.end),"avg_logprob":finite(s.avgLogprob),
                     "no_speech_prob":finite(s.noSpeechProb),"compression_ratio":finite(s.compressionRatio),
                     "temperature":finite(s.temperature),"token_count":s.tokens.count]
                }
                try emit(["id":id,"text":String(result.map(\.text).joined(separator:" ").trimmingCharacters(in:.whitespacesAndNewlines).prefix(2000)),
                    "confidence":["schema_version":1,"segments":scores,"segment_count":segments.count,
                        "segments_truncated":max(0,segments.count-64),
                        "min_avg_logprob":segments.map(\.avgLogprob).filter(\.isFinite).min().map { Double($0) } as Any? ?? NSNull(),
                        "word_probabilities_available":false,"interpretation":"uncalibrated decoder scores"],
                    "timing":["worker_transcribe_ms":ms,
                        // Vendor timings overlap: decodingLoop includes encoding.
                        "coreml_logmels_ms":result.reduce(0) { $0 + $1.timings.logmels*1000 },
                        "coreml_encoding_ms":result.reduce(0) { $0 + $1.timings.encoding*1000 },
                        "coreml_decoding_loop_inclusive_ms":result.reduce(0) { $0 + $1.timings.decodingLoop*1000 },
                        "coreml_decoding_predictions_ms":result.reduce(0) { $0 + $1.timings.decodingPredictions*1000 },
                        "coreml_decoding_non_prediction_ms":result.reduce(0) { $0 + $1.timings.decodingNonPrediction*1000 }]])
            } catch { try emit(["id":id,"error":"CoreMLTranscriptionFailed"]) }
        }
    }
}
