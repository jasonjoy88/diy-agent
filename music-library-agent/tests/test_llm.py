import unittest

from music_agent import llm
from music_agent.config import Config


class TestLlm(unittest.TestCase):
    def test_get_llm_returns_none_without_key(self):
        self.assertIsNone(llm.get_llm(Config(ark_api_key="", ark_model="")))

    def test_get_llm_returns_client_with_key(self):
        client = llm.get_llm(Config(ark_api_key="k", ark_model="m"))
        self.assertIsNotNone(client)
        self.assertEqual(client.model_name, "m")

    def test_ask_returns_none_without_key(self):
        self.assertIsNone(llm.ask("hello", Config(ark_api_key="", ark_model="")))


if __name__ == "__main__":
    unittest.main()
