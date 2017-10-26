import requests
import re
import pymongo
import string
import pickle
import outside_functions as of
from stop_words import get_stop_words
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from nltk.stem.wordnet import WordNetLemmatizer
from bs4 import BeautifulSoup

class TextPreprocessor(object):

    def __init__(self, stop_words = 'en', tfidf = True, lemmatize = False, vectorizer = None, lda_model = None):
        self.stop_words = get_stop_words(stop_words)
        self.tfidf = tfidf
        self.lemmatize = lemmatize
        if vectorizer != None:
            with open(vectorizer, 'rb') as f:
                self.vectorizer = pickle.load(f)
            print "loaded pickled vectorizer"
        else:
            self.vectorizer = vectorizer

        if lda_model != None:
            with open(lda_model, 'rb') as f:
                self.lda_model = pickle.load(f)
        else:
            self.lda_model = None

    def _launch_mongo(self, db_name, coll_name, uri):
        mc = pymongo.MongoClient(uri)
        db = mc[db_name]
        coll = db[coll_name]
        return coll

    def _gen_request(self, url):
        req = requests.get(str(url.strip()))
        if req.status_code != 200:
            print 'WARNING', req.status_code
            self.error_writer.writerow(('nyt', url))
        else:
            return req

    def _correct_sentences(self, text):
        add_spaces = re.sub(r'(?<=[.!?])(?=[^\s])', r' \n', text)
        return add_spaces

    def _encode_ascii(self, tokens):
        encoded = []
        for word in tokens:
            encoded.append(word.encode('ascii', 'ignore'))
        return encoded

    def _remove_stop_words(self, article):
        tokens = []
        for word in article.split():
            word = word.lower()
            word = word.strip(string.punctuation)
            tokens.append(word)
        stopped_tokens = [tok for tok in tokens if tok not in self.stop_words]
        return stopped_tokens

    def _lemmatize(self, tokens):
        lemmatizer = WordNetLemmatizer()
        lemmed = []
        for word in tokens:
            lem_word = lemmatizer.lemmatize(word)
            lemmed.append(word)
        return lemmed

    def _vectorize(self, tokens):
        vectorized = self.vectorizer.transform(tokens)

        return vectorized

    def _tokenize(self, article):
        stopped_tokens = self._remove_stop_words(article)
        encoded_tokens = self._encode_ascii(stopped_tokens)
        no_just_punc_tokens = [tok for tok in encoded_tokens if tok not in string.punctuation]

        return no_just_punc_tokens

    def _train_lda(self, vectorized_documents):
        lda = LatentDirichletAllocation(n_components = 300, learning_method = 'batch',
                                        max_iter = 50, n_jobs = -1, verbose = 5).fit(vectorized_documents)
        self.lda = lda

    # ----------- private methods above this line -----------

    def new_article(self, url):
        req = self._gen_request(url)
        soup = BeautifulSoup(req.text, 'html.parser')
        paragraphs = soup.find_all('p')
        article = ''
        for p in paragraphs:
            article = article + p.get_text()

        clean = self._correct_sentences(article)
        return clean

    def generate_vectors(self, article):
        cleaned_tokens = self._tokenize(article)
        if self.lemmatize:
            lemmed_tokens = self._lemmatize(cleaned_tokens)
            vectorized_tokens = self._vectorize(lemmed_tokens)
        else:
            vectorized_tokens = self._vectorize(cleaned_tokens)

        return self.vectorizer, vectorized_tokens

    def db_pipeline(self, processor_filepath, lda_model_filepath, db_name, coll_name, uri = None):
        coll = self._launch_mongo(db_name, coll_name, uri)
        all_docs = []
        error_counter, success = 0, 0
        for doc in coll.find(snapshot = True).batch_size(25):
            try:
                cleaned = self._correct_sentences(doc['article'])
                cleaned_tokens = self._tokenize(cleaned)
                if self.lemmatize:
                    lemmed_tokens = self._lemmatize(cleaned_tokens)
                    all_docs.append(lemmed_tokens)
                else:
                    all_docs.append(cleaned_tokens)
                success += 1
                print 'Success # {}'.format(success)
            except TypeError:
                error_counter += 1
                print 'TypeError, Moving On. Error #{}'.format(error_counter)

        if self.tfidf:
            self.vectorizer = TfidfVectorizer(preprocessor = of.tfidf_lambda,
                                              tokenizer = of.tfidf_lambda, max_df = 0.95).fit(all_docs)
        else:
            self.vectorizer = CountVectorizer(preprocessor = of.tfidf_lambda,
                                              tokenizer = of.tfidf_lambda, max_df = 0.95).fit(all_docs)

        print len(self.vectorizer.vocabulary_) , 'training lda'

        vectorized_docs = self.vectorizer.transform(all_docs)
        self._train_lda(vectorized_docs)

        print 'pickle-ing'

        with open(processor_filepath, 'wb') as f:
            pickle.dump(self.vectorizer, f)

        with open(lda_model_filepath, 'wb') as f:
            pickle.dump(self.lda_model)

        print "success TFIDF Vectorizer and LDA Model have been trained"

if __name__ == "__main__":
        db_name = 'articles_test_db'
        coll_name = 'article_text_data'
        uri = 'mongodb://root:TWV7Y1t7hS7P@localhost'
        processor_filepath = '/home/bitnami/processor.pkl'
        classifier_filepath = '/home/bitnami/naivebayesclassifier.pkl'
        lda_model = '/home/bitnami/lda_model.pkl'
        prep = TextPreprocessor()
        prep.db_pipeline(processor_filepath, lda_model, db_name, coll_name, uri)
