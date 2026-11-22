import importlib.util
import unittest
from pathlib import Path

HAS_AUDIO=importlib.util.find_spec('numpy') is not None and importlib.util.find_spec('onnxruntime') is not None

@unittest.skipUnless(HAS_AUDIO,'Optional local audio dependencies not installed')
class HeadTests(unittest.TestCase):
    def test_exported_head_matches_training_classifier(self):
        if importlib.util.find_spec('sklearn') is None:self.skipTest('Optional trainer not installed')
        import numpy as np
        from sklearn.neural_network import MLPClassifier
        from sklearn.preprocessing import StandardScaler
        from tavi.custom_wake import DenseHead
        rng=np.random.default_rng(42);x=rng.normal(size=(100,4));y=(x[:,0]>0).astype(int)
        scaler=StandardScaler().fit(x)
        model=MLPClassifier(hidden_layer_sizes=(6,),max_iter=500,random_state=42,tol=.01).fit(scaler.transform(x),y)
        weights={'mean':scaler.mean_,'scale':scaler.scale_}
        for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):weights[f'w{i}']=w;weights[f'b{i}']=b
        head=DenseHead(weights)
        expected=model.predict_proba(scaler.transform(x[:10]))[:,1]
        np.testing.assert_allclose([head.score(row) for row in x[:10]],expected,atol=1e-6)

    def test_frontend_rejects_wrong_size_and_returns_finite_features(self):
        if not Path('.tavi/models/custom/embedding_model.onnx').exists():self.skipTest('Public frontend not downloaded')
        import numpy as np
        from tavi.custom_wake import Features
        features=Features()
        with self.assertRaises(ValueError):features.extract(np.zeros(512,dtype=np.int16))
        result=features.extract(np.zeros(32000,dtype=np.int16))
        self.assertEqual(result.shape,(384,));self.assertTrue(np.isfinite(result).all())
        temporal=Features(mode='temporal').extract(np.zeros(32000,dtype=np.int16))
        self.assertEqual(temporal.shape,(1536,));self.assertTrue(np.isfinite(temporal).all())

    def test_missing_or_rejected_head_cannot_be_activated(self):
        import json,tempfile
        from unittest.mock import patch
        from tavi.custom_wake import CustomWake
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'head.json').write_text(json.dumps({'status':'rejected'}))
            with patch('tavi.custom_wake.Features'):
                with self.assertRaises(ValueError):CustomWake(root)

    def test_streaming_gate_is_required_for_live_activation(self):
        import json,tempfile
        from unittest.mock import patch
        from tavi.custom_wake import CustomWake
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'head.json').write_text(json.dumps({'status':'trial_candidate'}))
            with patch('tavi.custom_wake.Features'):
                with self.assertRaisesRegex(ValueError,'streaming'):CustomWake(root)

    def test_one_event_per_utterance_and_rearm_after_low_scores(self):
        import numpy as np
        from tavi.custom_wake import CustomWake
        detector=CustomWake.__new__(CustomWake);detector.threshold=.7;detector.reset()
        level=[.9];detector.probability=lambda audio:level[0]
        hits=sum(bool(detector.feed(bytes(1024))) for _ in range(30))
        self.assertEqual(hits,1)
        level[0]=.1
        for _ in range(60):detector.feed(bytes(1024))
        level[0]=.9
        self.assertEqual(sum(bool(detector.feed(bytes(1024))) for _ in range(10)),1)
        self.assertEqual(detector.audio.shape,(32000,))
        with self.assertRaises(ValueError):detector.feed(bytes(512))

    def test_exported_svm_matches_training_decision(self):
        if importlib.util.find_spec('sklearn') is None:self.skipTest('Optional trainer not installed')
        import numpy as np
        from sklearn.svm import SVC
        from sklearn.preprocessing import StandardScaler
        from tavi.custom_wake import DenseHead
        rng=np.random.default_rng(7);x=rng.normal(size=(80,4));y=(x[:,0]*x[:,1]>0).astype(int)
        scale=StandardScaler().fit(x);model=SVC(C=10,gamma=.1).fit(scale.transform(x),y)
        head=DenseHead({'mean':scale.mean_,'scale':scale.scale_,'sv':model.support_vectors_,'dual':model.dual_coef_[0],'intercept':model.intercept_[0],'gamma':model._gamma})
        expected=1/(1+np.exp(-model.decision_function(scale.transform(x[:10]))))
        np.testing.assert_allclose([head.score(row) for row in x[:10]],expected,atol=1e-6)

    def test_no_wake_without_recent_speech(self):
        from tavi.custom_wake import CustomWake
        detector=CustomWake.__new__(CustomWake);detector.threshold=.5;detector.reset();detector.probability=lambda audio:.99
        self.assertFalse(any(detector.feed(bytes(1024),speech_allowed=False) for _ in range(50)))
        self.assertEqual(sum(bool(detector.feed(bytes(1024),speech_allowed=True)) for _ in range(10)),1)
