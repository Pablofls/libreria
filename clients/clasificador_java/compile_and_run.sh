#!/bin/bash
# Compila y ejecuta Cloud Models Classifier (GUI)
set -e

mkdir -p out

javac -encoding UTF-8 -d out \
  src/classifier/CloudModel.java \
  src/classifier/ClassificationException.java \
  src/classifier/ClassificationResult.java \
  src/classifier/nlp/TextPreprocessor.java \
  src/classifier/CloudClassifier.java \
  src/gui/AppWindow.java \
  src/Main.java \
  src/CloudClassifierCLI.java

echo "Compilación exitosa. Iniciando interfaz gráfica..."
java -cp out Main
