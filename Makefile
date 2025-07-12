IMAGE_NAME ?= etandelxyz

SITE_FILES ?= ./blog/* ./css/* ./images/* ./templates/*

site: .stack-work/dist/x86_64-linux-tinfo6/Cabal-2.0.1.0/build/site/site
	@.stack-work/dist/x86_64-linux-tinfo6/Cabal-2.0.1.0/build/site/site build

.stack-work/dist/x86_64-linux-tinfo6/Cabal-2.0.1.0/build/site/site: $(SITE_FILES)
	@stack build

.PHONY: build-docker
build-docker: site
	docker image build -t '$(IMAGE_NAME)' .

.PHONY: run-docker
run-docker: build-docker
	docker run -p 80:80 '$(IMAGE_NAME)'

deploy-flyio: build-docker
	flyctl deploy

deploy-aws: site
	@rsync -avz _site/ etandel.xyz:/usr/share/nginx/etandel.xyz
