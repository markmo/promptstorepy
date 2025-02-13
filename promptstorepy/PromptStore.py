import os
import json
import logging
import requests
from devtools import debug
from uuid import uuid4

from .ApiService import ApiService
from .KeycloakAuth import KeycloakAuth
from .utils import get_search_type, strip_empty_values


class PromptStore:
    def __init__(self, constants=None, logger=None, callback=None):
        self.constants = constants or {}
        self.logger = logger or logging.getLogger(__name__)
        self.url = self.constants.get(
            "PROMPTSTORE_BASE_URL", os.getenv("PROMPTSTORE_BASE_URL")
        )
        self.workspace_id = self.constants.get(
            "WORKSPACE_ID", os.getenv("WORKSPACE_ID")
        )
        self.functions = {}
        self.api_service = ApiService()

        auth_method = self.constants.get("AUTH_METHOD", os.getenv("AUTH_METHOD"))
        if auth_method and auth_method.lower() == "oauth":
            self.auth = KeycloakAuth(self.constants, self.logger)
            token = self.auth.get_access_token()
            self.api_service.set_token(token)
            if callable(callback):
                callback()

    def trace(self, event):
        debug(f"trace [event={json.dumps(event)}]")
        self.logger.debug(f"trace [event={json.dumps(event)}]")
        try:
            url = f"{self.url}/traces"
            event = {**event, "workspaceId": self.workspace_id}
            res = self.api_service.post(url, json=event)
            # debug(res.json())
            return res.json()
        except requests.RequestException as err:
            debug(err)
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def add_function(self, name, params, content_only=False):
        self.logger.debug(
            f"addFunction [name={name}; params={json.dumps(params)}; contentOnly={content_only}]"
        )

        async def func(args, param_overrides=None):
            param_overrides = param_overrides or {}
            try:
                url = f"{self.url}/executions/{name}"
                options = {
                    "args": args,
                    "params": {**params, **strip_empty_values(param_overrides)},
                    "workspaceId": self.workspace_id,
                }
                self.logger.debug(f"url: {url}, options: {options}")
                res = self.api_service.post(url, json=options)
                data = res.json()
                if data.get("errors"):
                    return {"errors": data["errors"]}
                if content_only:
                    message = data["response"]["choices"][0]["message"]
                    if message.get("function_call"):
                        try:
                            return json.loads(message["function_call"]["arguments"])
                        except json.JSONDecodeError as err:
                            self.logger.error(f"error parsing json response: {err}")
                            return {}
                    else:
                        return message["content"]
                return data
            except requests.RequestException as err:
                self.logger.error(str(err))
                if err.response and err.response.json().get("errors"):
                    return err.response.json()
                return {"errors": [{"message": str(err)}]}

        setattr(self, name, func)
        return func

    def execute(
        self,
        name,
        args,
        params,
        history=None,
        messages=None,
        content_only=False,
    ):
        self.logger.debug(
            f"execute [name={name}; args={json.dumps(args)}; params={json.dumps(params)}; contentOnly={content_only}]"
        )
        try:
            url = f"{self.url}/executions/{name}"
            options = {
                "args": args,
                "params": params,
                "history": history,
                "messages": messages,
                "workspaceId": self.workspace_id,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            data = res.json()
            if data.get("errors"):
                return {"errors": data["errors"]}
            if content_only:
                message = data["response"]["choices"][0]["message"]
                if message.get("function_call"):
                    try:
                        return json.loads(message["function_call"]["arguments"])
                    except json.JSONDecodeError as err:
                        self.logger.error(f"error parsing json response: {err}")
                        return {}
                else:
                    return message["content"]
            return data
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def execute_composition(self, name, args, params, functions):
        self.logger.debug(
            f"executeComposition [name={name}; args={json.dumps(args)}; params={json.dumps(params)}; functions={json.dumps(functions)}]"
        )
        try:
            url = f"{self.url}/composition-executions/{name}"
            options = {
                "args": args,
                "params": params,
                "functions": functions,
                "workspaceId": self.workspace_id,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def call_tool(self, name, args, raw):
        self.logger.debug(f"callTool [name={name}; args={json.dumps(args)}; raw={raw}]")
        try:
            url = f"{self.url}/tool-executions/{name}"
            options = {"args": args, "raw": raw}
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def chat_completion(self, messages, model, max_tokens, index_name):
        self.logger.debug(
            f"chatCompletion [messages={json.dumps(messages)}; model={model}; maxTokens={max_tokens}; indexName={index_name}]"
        )
        try:
            url = f"{self.url}/chat"
            options = {
                "messages": messages,
                "model": model,
                "maxTokens": max_tokens,
                "indexName": index_name,
                "workspaceId": self.workspace_id,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def create_embeddings(self, embedding_provider, embedding_model, chunks):
        self.logger.debug(
            f"createEmbeddings [embeddingProvider={embedding_provider}; embeddingModel={embedding_model}]"
        )
        try:
            url = f"{self.url}/embeddings/{embedding_provider}"
            options = {
                "chunks": chunks,
                "embeddingModel": embedding_model,
                "embeddingProvider": embedding_provider,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def create_image(self, prompt, n=1, size="1024x1024"):
        self.logger.debug(f"createImage [prompt={prompt}; n={n}; size={size}]")
        try:
            url = f"{self.url}/image-request"
            options = {
                "sourceId": self.workspace_id,
                "prompt": prompt,
                "size": size,
                "n": n,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def generate_image_variant(self, image_url, n=1):
        self.logger.debug(f"generateImageVariant [imageUrl={image_url}; n={n}]")
        try:
            url = f"{self.url}/gen-image-variant"
            options = {"imageUrl": image_url, "n": n, "workspaceId": self.workspace_id}
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_functions_by_tag(self, tag):
        self.logger.debug(
            f"getFunctionsByTag [workspaceId={self.workspace_id}; tag={tag}]"
        )
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/functions/tags/{tag}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_compositions(self):
        self.logger.debug(f"getCompositions [workspaceId={self.workspace_id}]")
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/compositions"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_composition(self, composition_id):
        self.logger.debug(f"getComposition [id={composition_id}]")
        try:
            url = f"{self.url}/compositions/{composition_id}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_prompt_set(self, skill: str):
        self.logger.debug(f"getPromptSet [skill={skill}]")
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/prompt-sets?skill={skill}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            pss = res.json()
            self.logger.debug(f"pss: {pss}")
            self.logger.debug(f"len: {len(pss)}")
            if len(pss) > 0:
                return pss[0]
            return None
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_prompt_sets(self):
        self.logger.debug("getPromptSets")
        try:
            url = f"{self.url}/prompt-sets"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_workspace_prompt_sets(self):
        self.logger.debug(f"getWorkspacePromptSets [workspaceId={self.workspace_id}]")
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/prompt-sets"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_workspace_prompt_sets_by_skill(self, skill):
        self.logger.debug(
            f"getWorkspacePromptSetsBySkill [workspaceId={self.workspace_id}; skill={skill}]"
        )
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/prompt-sets?skill={skill}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_indexes(self):
        self.logger.debug(f"getIndexes [workspaceId={self.workspace_id}]")
        try:
            url = f"{self.url}/workspaces/{self.workspace_id}/indexes"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_index(self, vector_store_provider, index_name):
        self.logger.debug(
            f"getIndex [vectorStoreProvider={vector_store_provider}; indexName={index_name}]"
        )
        try:
            url = f"{self.url}/index/{vector_store_provider}/{index_name}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.get(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def create_index(self, vector_store_provider, index_name, schema, params):
        self.logger.debug(
            f"createIndex [vectorStoreProvider={vector_store_provider}; indexName={index_name}; schema={json.dumps(schema)}; params={json.dumps(params)}]"
        )
        try:
            url = f"{self.url}/index"
            options = {
                "indexName": index_name,
                "schema": schema,
                "params": params,
                "vectorStoreProvider": vector_store_provider,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def drop_index(self, vector_store_provider, index_name):
        self.logger.debug(
            f"dropIndex [vectorStoreProvider={vector_store_provider}; indexName={index_name}]"
        )
        try:
            url = f"{self.url}/index/{vector_store_provider}/{index_name}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.delete(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def add_document(self, filepath):
        self.logger.debug(f"addDocument [filepath={filepath}]")
        try:
            correlation_id = str(uuid4())
            filename = os.path.basename(filepath)
            mimetype = mimetypes.guess_type(filepath)[0]
            with open(filepath, "rb") as file:
                files = {
                    "file": (filename, file, mimetype),
                }
                data = {
                    "sourceId": self.workspace_id,
                    "correlationId": correlation_id,
                }
                url = f"{self.url}/upload/"
                self.logger.debug(f"url: {url}, files: {files}, data: {data}")
                res = self.api_service.post(url, files=files, data=data)
                self.logger.debug("File uploaded to document service successfully.")
                return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def index_documents(self, index_name, documents):
        self.logger.debug(f"indexDocuments [indexName={index_name}]")
        try:
            url = f"{self.url}/documents"
            self.logger.debug(f"url: {url}")
            res = self.api_service.post(
                url, json={"indexName": index_name, "documents": documents}
            )
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def drop_documents(self, index_name, query, attrs):
        self.logger.debug(
            f"dropDocuments [indexName={index_name}; query={query}; attrs={json.dumps(attrs)}]"
        )
        try:
            query_params = "&".join([f"{k}={v}" for k, v in attrs.items()])
            url = f"{self.url}/delete-matching?indexName={index_name}"
            if query:
                url += f"&q={query}"
            if query_params:
                url += f"&{query_params}"
            self.logger.debug(f"url: {url}")
            res = self.api_service.delete(url)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def index_chunks(self, vector_store_provider, chunks, embeddings, params):
        self.logger.debug(
            f"indexChunks [vectorStoreProvider={vector_store_provider}; params={json.dumps(params)}]"
        )
        try:
            url = f'{self.url}/chunks/{vector_store_provider}/{params["indexName"]}'
            options = {"chunks": chunks, "embeddings": embeddings, "params": params}
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def delete_chunks(self, vector_store_provider, ids, params):
        self.logger.debug(
            f"deleteChunks [vectorStoreProvider={vector_store_provider}; ids={ids}; params={json.dumps(params)}]"
        )
        try:
            url = f"{self.url}/bulk-delete"
            options = {
                "ids": ids,
                "params": params,
                "vectorStoreProvider": vector_store_provider,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def delete_chunk(self, vector_store_provider, chunk_id, params):
        self.logger.debug(
            f"deleteChunk [vectorStoreProvider={vector_store_provider}; id={chunk_id}; params={json.dumps(params)}]"
        )
        try:
            url = f"{self.url}/bulk-delete"
            options = {
                "ids": [chunk_id],
                "params": params,
                "vectorStoreProvider": vector_store_provider,
            }
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def search(self, params):
        self.logger.debug(f"search [params={json.dumps(params)}]")
        try:
            url = f"{self.url}/search"
            options = {**params, "workspaceId": 1}
            self.logger.debug(f"url: {url}, options: {options}")
            res = self.api_service.post(url, json=options)
            return res.json()
        except requests.RequestException as err:
            self.logger.error(str(err))
            if err.response and err.response.json().get("errors"):
                return err.response.json()
            return {"errors": [{"message": str(err)}]}

    def get_search_schema(self, schema):
        self.logger.debug(f"getSearchSchema [schema={json.dumps(schema)}]")
        try:
            fields = {}
            for k, v in schema.items():
                for key, val in v.items():
                    fields[f"{k.lower()}_{key.lower()}"] = {
                        "type": get_search_type(val["dataType"])
                    }
                fields[f"{k.lower()}__label"] = {"type": "TEXT"}
            return fields
        except Exception as err:
            self.logger.error(str(err))
            return {"errors": [{"message": str(err)}]}
